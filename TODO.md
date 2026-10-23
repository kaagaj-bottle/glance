# TODO

- **Flatpak: deliver the Google Lens page over loopback.** `google_results` in
  `src/glance/search/engines.py` writes an HTML page to the sandbox's `/tmp` and opens
  it as a `file://` URL. A Flatpak sandbox's `/tmp` is private, and a sandboxed browser
  can't read host paths, so this will not open. Serve the page once on
  `127.0.0.1:<random port>` (stdlib `http.server`), open `http://127.0.0.1:<port>/`
  through the OpenURI portal, and keep the app alive until the browser has fetched it
  instead of waiting a fixed `SEARCH_EXIT_MS`. Needs `--share=network`, which the
  uploads need anyway.

- **Flatpak: let Wi-Fi codes reach NetworkManager.** `src/glance/wifi.py` talks to
  `org.freedesktop.NetworkManager` on the system bus, and `src/glance/notify.py` to
  `org.freedesktop.Notifications` on the session bus. A sandbox needs
  `--system-talk-name=org.freedesktop.NetworkManager` and
  `--talk-name=org.freedesktop.Notifications` (or the notification portal instead).

- **Flatpak: hand contact and calendar files to the host.** `write_document` in
  `src/glance/app.py` writes the `.vcf` / `.ics` file to the cache folder and opens it
  with `QDesktopServices`. A sandboxed cache folder is not visible to the host's
  contacts or calendar app, so, like the Google Lens page above, this should go through
  the OpenURI portal (`OpenFile`, which passes a file descriptor).

- **Flatpak: let recordings reach the Videos folder.** `recording_path` in
  `src/glance/app.py` writes to `~/Videos/Screencasts`, and the recorder's `gst-launch-1.0`
  process runs inside the sandbox. It needs `--filesystem=xdg-videos` (or a file chooser
  through the documents portal), and the GStreamer `vpx` and `matroska` plugins in the
  runtime.

- **Flatpak: keep the recording frame working.** `src/glance/ui/guide.py` draws the
  dashed frame and the Stop bar with a helper process on X11, since Wayland cannot place a window. A
  sandbox needs `--socket=fallback-x11` (and `--share=ipc`) for it. A Wayland-only build
  would show no frame, so find a different way to mark the area, such as the compositor's
  own recording indicator or a layer-shell overlay where one exists.
