# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it privately rather than opening a public issue.

**Email:** aakash.lohchab97@gmail.com

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

## Sensitive Data

This tool handles:
- **Zoom recording URLs** — contain time-limited signed tokens
- **Recording passcodes** — entered by the user
- **Proxy credentials** — stored in `.env`

### What we do

- Proxy passwords are masked (`****`) in all terminal output
- `.env` is excluded from version control via `.gitignore`
- No data is sent to third parties — all traffic goes directly to Zoom's servers (or through the user's configured proxy)
- No telemetry, analytics, or tracking of any kind

### What you should do

- Never commit your `.env` file
- Use `.env.example` as a reference — it contains no real values
- Rotate proxy credentials if you suspect they were exposed
