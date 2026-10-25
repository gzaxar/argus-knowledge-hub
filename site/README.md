# ARGUS Knowledge Hub public site

This site combines bilingual product pages and a public manual. It is built for GitHub Pages at
`https://infn-argus.github.io/argus-knowledge-hub/`.

The detailed manual is generated from `backend/app/help/guide/*.md`, the same chapters used by
the application’s Help feature. Edit those files to update both manuals. English and Italian
navigation, marketing pages and getting started steps live in `build.mjs`; detailed manuals
currently use the English source text in both language shells and are labeled accordingly.

To build locally:

```sh
cd site
npm ci
npm run build
```

The output is `site/dist/`, which the GitHub Actions workflow publishes. The application and
the project overview site are linked from the public site.
