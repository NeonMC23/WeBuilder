# Security policy

## Supported line

WeBuilder CLI v1 receives critical correctness and security fixes through patch releases. New product features are reserved for v2.

## Reporting a vulnerability

Do not publish sensitive vulnerability details in a public issue. Use the private security-reporting mechanism of the repository or contact the project maintainer privately. Include:

- affected WeBuilder version;
- operating system and Python version;
- a minimal configuration or plugin that reproduces the issue;
- expected and observed behavior;
- impact assessment;
- suggested mitigation, if available.

## Trust boundaries

WeBuilder is a developer tool that compiles trusted project input:

- `events` values are emitted as executable JavaScript;
- component and plugin `js` fields are executable JavaScript;
- triple-brace Mustache values inject raw HTML;
- component and plugin CSS is emitted as authored.

Do not build untrusted `build.json`, `library.json`, or plugin files without reviewing them.

WeBuilder validates page paths, asset paths, plugin namespaces, arbitrary utility values, and output-directory safety. These checks reduce accidental or malicious file-system and CSS injection risks, but they do not sandbox intentionally executable HTML, CSS, or JavaScript content.
