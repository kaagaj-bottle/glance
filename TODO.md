# TODO

- **Flatpak: deliver the Google Lens page over loopback.** `google_results` in
  `src/glance/search/engines.py` writes an HTML page to the sandbox's `/tmp` and opens
  it as a `file://` URL. A Flatpak sandbox's `/tmp` is private, and a sandboxed browser
  can't read host paths, so this will not open. Serve the page once on
  `127.0.0.1:<random port>` (stdlib `http.server`), open `http://127.0.0.1:<port>/`
  through the OpenURI portal, and keep the app alive until the browser has fetched it
  instead of waiting a fixed `SEARCH_EXIT_MS`. Needs `--share=network`, which the
  uploads need anyway.
