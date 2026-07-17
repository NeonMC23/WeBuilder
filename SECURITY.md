# Security policy

## Supported line

The current WeBuilder v2 line receives correctness and security fixes. The stable v1 CLI behavior remains supported inside v2 for build compatibility.

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

WeBuilder validates page paths, asset paths, plugin namespaces, arbitrary utility values, and output-directory safety. The visual editor additionally confines static and preview paths, restricts mutating requests to trusted local hosts and same-origin browser sessions, limits upload sizes, sanitizes filenames, and performs atomic saves with backups.

These checks reduce accidental or malicious file-system, request, and CSS injection risks, but they do not sandbox intentionally executable HTML, CSS, or JavaScript content. The GUI should remain bound to loopback unless the operator explicitly accepts LAN exposure.
