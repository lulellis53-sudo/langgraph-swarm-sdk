//! `websearch-rs`: query the local SearXNG JSON API and print ranked hits.

use std::time::Duration;

use anyhow::{Context, Result, bail};
use clap::Parser;
use serde::{Deserialize, Serialize};

#[derive(Parser, Debug)]
#[command(version, about = "Query SearXNG with dork operators")]
struct Cli {
    /// Free-text query.
    query: String,
    /// SearXNG base URL.
    #[arg(long, env = "SEARXNG_URL", default_value = "http://127.0.0.1:8888")]
    base_url: String,
    /// Maximum hits to print.
    #[arg(long, default_value_t = 10)]
    limit: usize,
    /// Restrict to a site (`site:`).
    #[arg(long)]
    site: Option<String>,
    /// Restrict to a file type (`filetype:`).
    #[arg(long)]
    filetype: Option<String>,
    /// Require a phrase in the title (`intitle:`).
    #[arg(long)]
    intitle: Option<String>,
    /// Exclude a term (`-term`); repeatable.
    #[arg(long)]
    exclude: Vec<String>,
    /// Comma-separated SearXNG engines.
    #[arg(long)]
    engines: Option<String>,
    /// Request timeout in seconds.
    #[arg(long, default_value_t = 20)]
    timeout: u64,
    /// Emit JSON instead of text.
    #[arg(long)]
    json: bool,
}

#[derive(Debug, Deserialize)]
struct Response {
    #[serde(default)]
    results: Vec<RawHit>,
}

#[derive(Debug, Deserialize)]
struct RawHit {
    #[serde(default)]
    title: String,
    #[serde(default)]
    url: String,
    #[serde(default)]
    content: String,
    #[serde(default)]
    engine: String,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
struct Hit {
    title: String,
    url: String,
    snippet: String,
    engine: String,
}

fn reject_operator_injection(field: &str, value: &str) -> Result<()> {
    if value.chars().any(|c| c.is_whitespace() || c == '"') {
        bail!("--{field} must not contain whitespace or quotes: {value:?}");
    }
    Ok(())
}

/// Compose the final query string from the free text and dork flags.
fn build_query(cli: &Cli) -> Result<String> {
    let mut parts = vec![cli.query.trim().to_string()];
    for (name, value, op) in [
        ("site", &cli.site, "site"),
        ("filetype", &cli.filetype, "filetype"),
    ] {
        if let Some(v) = value {
            reject_operator_injection(name, v)?;
            parts.push(format!("{op}:{v}"));
        }
    }
    if let Some(v) = &cli.intitle {
        parts.push(format!("intitle:\"{}\"", v.replace('"', "")));
    }
    for term in &cli.exclude {
        reject_operator_injection("exclude", term)?;
        parts.push(format!("-{term}"));
    }
    Ok(parts.join(" "))
}

/// Keep only http(s) hits, drop duplicate URLs, and cap at `limit`.
fn clean_hits(raw: Vec<RawHit>, limit: usize) -> Vec<Hit> {
    let mut seen = std::collections::HashSet::new();
    raw.into_iter()
        .filter(|h| h.url.starts_with("http://") || h.url.starts_with("https://"))
        .filter(|h| seen.insert(h.url.clone()))
        .take(limit)
        .map(|h| Hit {
            title: h.title.trim().to_string(),
            url: h.url,
            snippet: h.content.trim().to_string(),
            engine: h.engine,
        })
        .collect()
}

fn render_text(hits: &[Hit]) -> String {
    hits.iter()
        .enumerate()
        .map(|(i, h)| format!("{}. {}\n   {}\n   {}", i + 1, h.title, h.url, h.snippet))
        .collect::<Vec<_>>()
        .join("\n")
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let query = build_query(&cli)?;
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(cli.timeout))
        .user_agent(concat!("websearch-rs/", env!("CARGO_PKG_VERSION")))
        .build()
        .context("building HTTP client")?;
    let endpoint = format!("{}/search", cli.base_url.trim_end_matches('/'));
    let mut request = client
        .get(&endpoint)
        .query(&[("q", query.as_str()), ("format", "json")]);
    if let Some(engines) = &cli.engines {
        request = request.query(&[("engines", engines.as_str())]);
    }
    let response: Response = request
        .send()
        .with_context(|| format!("requesting {endpoint}"))?
        .error_for_status()
        .context("SearXNG returned an error status")?
        .json()
        .context("decoding SearXNG JSON")?;
    let hits = clean_hits(response.results, cli.limit);
    if hits.is_empty() {
        eprintln!("no results for: {query}");
        std::process::exit(1);
    }
    if cli.json {
        println!("{}", serde_json::to_string_pretty(&hits)?);
    } else {
        println!("{}", render_text(&hits));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cli(args: &[&str]) -> Cli {
        Cli::parse_from(std::iter::once("websearch-rs").chain(args.iter().copied()))
    }

    #[test]
    fn query_includes_dork_operators() {
        let c = cli(&["rust async", "--site", "docs.rs", "--filetype", "pdf", "--exclude", "tokio"]);
        assert_eq!(build_query(&c).unwrap(), "rust async site:docs.rs filetype:pdf -tokio");
    }

    #[test]
    fn operator_values_reject_injection() {
        let c = cli(&["x", "--site", "a.com OR b.com"]);
        assert!(build_query(&c).is_err());
    }

    #[test]
    fn intitle_strips_quotes() {
        let c = cli(&["x", "--intitle", "a\"b"]);
        assert_eq!(build_query(&c).unwrap(), "x intitle:\"ab\"");
    }

    #[test]
    fn clean_hits_dedupes_filters_and_limits() {
        let raw = |u: &str| RawHit {
            title: " T ".into(),
            url: u.into(),
            content: String::new(),
            engine: "ddg".into(),
        };
        let hits = clean_hits(
            vec![raw("https://a.com"), raw("https://a.com"), raw("javascript:x"), raw("http://b.com")],
            5,
        );
        assert_eq!(hits.iter().map(|h| h.url.as_str()).collect::<Vec<_>>(), ["https://a.com", "http://b.com"]);
        assert_eq!(hits[0].title, "T");
        assert_eq!(clean_hits(vec![raw("https://a.com"), raw("https://b.com")], 1).len(), 1);
    }

    #[test]
    fn response_tolerates_missing_fields() {
        let r: Response = serde_json::from_str(r#"{"results":[{"url":"https://x.io"}]}"#).unwrap();
        assert_eq!(r.results.len(), 1);
        assert_eq!(serde_json::from_str::<Response>("{}").unwrap().results.len(), 0);
    }
}
