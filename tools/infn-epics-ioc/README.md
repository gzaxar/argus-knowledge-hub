# Publishing the IOC catalogue from infn-epics-ioc

`ioc-catalog.patch` adds two things to infn-epics-ioc:

- `.github/workflows/ioc-catalog.yml`: on every `v*` tag it builds `ioc-catalog.json.gz` with this repository's
  builder (`backend/app/ioc_engineer`) and attaches it to the release; on pushes to main it keeps the
  catalogue as an artifact;
- section 10 of `docs/architecture.md`, which describes the workflow.

Apply it in a checkout of infn-epics-ioc:

```bash
git am /path/to/argus-knowledge-hub/tools/infn-epics-ioc/ioc-catalog.patch
git push
```

Then point the hub at the release asset:

```
ARGUS_IOC_CATALOG=https://github.com/infn-epics/infn-epics-ioc/releases/latest/download/ioc-catalog.json.gz
```

The workflow uses the builder from argus-knowledge-hub `main` (repository variable `ARGUS_REF` to change it),
so merge the IOC engineer into main first. The repository variable `IOC_CATALOG_BEAMLINES` sets which beamline
repositories it reads. Its default is ELI-NP. See docs/ioc-engineer.md.
