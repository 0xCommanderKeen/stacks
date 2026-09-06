# Three Stacks design directions

Interactive, dependency-free design prototypes for owner selection. These are
sample interfaces, not replacements for the working app or an implementation of
all backend features. No library data is read or changed.

- A — Clear: light sidebar, cover grid, compact reading/listening continuation.
- B — After hours: dark media home, featured listening and next-up selection.
- C — Index: horizontal navigation, dense catalog rows, persistent desktop inspector.

Run from the repository root:

```sh
python3 -m http.server 8134 --bind 127.0.0.1 --directory design/variants
```

Open `http://localhost:8134` and use the A/B/C switcher. Each direction supports
sample search, format filters, details, navigation, and a real 20-second sample
audio player. File selection explicitly does not import anything. Settings are
illustrative. The covers and publication names are original synthetic fixtures;
the recording is copied from the existing Stacks test fixture.

Checked in Chromium at 1440px and 390px: no horizontal page overflow, search,
format filtering, and book details. Desktop layouts were visually inspected.
Mobile Index opens details directly because its inspector is hidden.

Keep these alternatives separate from the product until the owner picks a direction.
