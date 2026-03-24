# How We Solved the Zoom Recording Download Issue

## The Problem

We had a Zoom cloud recording share link with an embedded passcode and needed to download the `.mp4` file programmatically. Sounds simple — it wasn't.

**Link format:** `https://us06web.zoom.us/rec/share/<share_id>?pwd=<passcode>`

---

## What We Tried (and Why It Failed)

### Attempt 1: `zoom-rec-dl` (npm tool)

```bash
npx zoom-rec-dl@latest
```

**Result:** `File ID is not found.`

**Why it failed:** The tool stripped the `?pwd=` query parameter during URL parsing. The passcode contained special characters (`%` and `$`) that caused encoding issues. Additionally, the tool expects the share link to resolve to a direct player page, but Zoom's newer SPA architecture returns a React app that requires JavaScript to render.

### Attempt 2: Direct HTTP Request (Python `urllib`)

Fetched the share page HTML and searched for download URLs like `viewMp4Url`, `downloadUrl`, or `play_url`.

**Result:** The page HTML was 514KB of React/JavaScript bundle code. The `fileId` field was empty, and no video URLs existed in the raw HTML.

**Why it failed:** Zoom's recording pages are fully client-side rendered (React SPA). The actual recording data is loaded dynamically via JavaScript API calls after the page mounts and the passcode is validated.

### Attempt 3: Zoom's Password Validation API

Tried submitting the passcode via Zoom's internal APIs:

- `POST /nws/recording/1.0/validate-context` → `"Missing Request Parameters"`
- `POST /rec/validate_share_passwd` → `404 Not Found`
- `GET /nws/recording/1.0/play/share-info/<share_id>` → `"componentName": "need-password"`
- `GET /nws/recording/1.0/play/info/<share_id>` → `"This recording does not exist."`

**Why it failed:** Zoom's API requires specific undocumented request formats, CSRF tokens, and session cookies that are set by their JavaScript client. Without running their JS, you can't properly authenticate.

### Attempt 4: Playwright Browser Automation (First Try)

Used Playwright (headless Chromium) to load the page, fill in the passcode, and click "Watch Recording."

**Result:** The passcode was accepted! The page title changed to the recording name. We successfully extracted the video source URL from the `<video>` element:

```
https://ssrweb.zoom.us/replay02/2026/01/20/<meeting_id>/GMT20260120-132516_Recording_gallery_1832x982.mp4?...
```

But downloading the video failed:

- **`page.request.get()`** → 0 bytes (Playwright's API request didn't handle the streaming response)
- **`fetch()` from page context** → `"Failed to fetch"` (CORS blocked — `ssrweb.zoom.us` rejects cross-origin requests from `us06web.zoom.us`)
- **curl with cookies** → 0 bytes or HTML error page (cookies were for `zoom.us` domain, not `ssrweb.zoom.us`; signed URL tokens may have expired)

### The Passcode Encoding Problem

A sub-issue: a passcode like `ab%50x$Y` gets misinterpreted at every layer:

| Layer | Interpretation | Actual password |
|-------|---------------|-----------------|
| URL parser | `%50` → `P`, giving `abPx$Y` | Wrong |
| Shell | `$Y` → empty variable, giving `ab%50x` | Wrong |
| Literal string | `ab%50x$Y` as-is | **Correct** |

The `%50` was literally part of the passcode, not a URL-encoded character. This caused the first several attempts to submit the wrong password. Playwright confirmed it: **"Wrong passcode"** displayed on the page.

---

## The Solution That Worked

### Key Insight

The video is served from `ssrweb.zoom.us` via **AWS CloudFront signed URLs**. The URL contains embedded authentication:

- `Policy` — base64-encoded access policy
- `Signature` — cryptographic signature
- `Key-Pair-Id` — CloudFront key pair identifier

These tokens are **self-contained** — no cookies needed. The browser fetches the video using `HTTP Range Requests` (status `206 Partial Content`), streaming it in chunks. But you can force a full download by requesting `Range: bytes=0-`.

### The Working Approach

**Step 1:** Use Playwright to authenticate and capture the real video URL

```python
# Intercept the actual network request the browser makes
video_request_info = {}

def capture_request(request):
    if "ssrweb" in request.url and ".mp4" in request.url:
        video_request_info["url"] = request.url
        video_request_info["headers"] = request.headers

page.on("request", capture_request)
```

This captures the full 1873-character signed URL when the `<video>` element starts loading the stream.

**Step 2:** Close the browser and download with `curl` using `Range: bytes=0-`

```bash
curl -L \
  -o video.mp4 \
  -H "Range: bytes=0-" \
  -H "Referer: https://us06web.zoom.us/" \
  -H "User-Agent: Mozilla/5.0 ..." \
  "https://ssrweb.zoom.us/replay02/.../Recording.mp4?Policy=...&Signature=...&Key-Pair-Id=..."
```

The `Range: bytes=0-` header is critical — it tells the server to return the **entire file** from byte 0 to the end, instead of the small chunks the browser normally requests.

**Result:** 223.8 MB MP4 file downloaded successfully in ~35 seconds.

---

## Architecture Diagram

```
┌─────────────┐     passcode      ┌──────────────────┐
│  Playwright  │ ───────────────→  │  us06.zoom.us    │
│  (headless)  │ ←─────────────── │  (React SPA)     │
│              │   session cookies │                  │
│              │                   │  Validates pwd   │
│              │                   │  Renders player  │
│              │                   │  Generates signed│
│              │                   │  CloudFront URL  │
└──────┬───────┘                   └──────────────────┘
       │
       │ captures request to:
       │ ssrweb.zoom.us/replay02/...mp4?Policy=...&Signature=...
       │
       ▼
┌─────────────┐  Range: bytes=0-  ┌──────────────────┐
│    curl      │ ───────────────→  │  ssrweb.zoom.us  │
│              │ ←─────────────── │  (CloudFront CDN) │
│              │   206 Partial    │                  │
│              │   (full file)    │  Serves MP4 via  │
│              │                   │  signed URL auth │
└──────────────┘                   └──────────────────┘
       │
       ▼
   video.mp4 (223.8 MB)
```

---

## Why Other Tools Failed

| Tool | Failure Reason |
|------|---------------|
| `zoom-rec-dl` | Strips query params; can't handle SPA pages |
| Direct HTTP/urllib | Zoom pages are React SPAs; no video URLs in raw HTML |
| Zoom API calls | Undocumented, requires JS-generated CSRF tokens |
| `fetch()` in browser | CORS blocks cross-origin requests to `ssrweb.zoom.us` |
| curl with cookies only | Signed URL tokens are in the URL, not cookies; tokens expire fast |

---

## Lessons Learned

1. **Zoom recordings are React SPAs** — you can't scrape them with simple HTTP requests. You need a real browser (or headless browser) to render the JavaScript.

2. **The passcode might contain literal URL-encoding characters** — `%50` can be part of the password itself, not a URL-encoded `P`. Always treat passcodes as opaque strings.

3. **CloudFront signed URLs are self-authenticating** — the `Policy`, `Signature`, and `Key-Pair-Id` query parameters contain all the auth. No cookies needed for the actual video download.

4. **`Range: bytes=0-` forces full download** — video servers that use HTTP Range Requests (206) will serve the entire file if you request from byte 0 to end.

5. **Capture the browser's actual network request** — instead of trying to reconstruct the URL from page HTML, intercept what the browser actually sends. Playwright's `page.on("request")` is perfect for this.

6. **The signed URL expires quickly** — you need to capture it and start downloading immediately. Don't close the browser, go make coffee, and then try to curl it.

---

## Final Script Summary

The working script (`download_zoom.py`) does this:

1. Launches headless Chromium via Playwright
2. Navigates to the Zoom share page
3. Fills in the passcode and submits
4. Sets up a request interceptor for `ssrweb.zoom.us/*.mp4` URLs
5. Waits for the video player to load and start fetching the video stream
6. Captures the full signed CloudFront URL (with Policy, Signature, Key-Pair-Id)
7. Closes the browser
8. Downloads the full MP4 using `curl -H "Range: bytes=0-"` with the captured URL

**Total time:** ~35 seconds (including browser automation + 223.8 MB download)
