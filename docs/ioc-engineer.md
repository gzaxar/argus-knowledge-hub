# The IOC engineer

ARGUS can help people build, configure and debug containerised EPICS IOCs. At INFN every hardware IOC runs
from one generic image, `infn-epics-ioc`. What makes that image into a specific IOC is written in two of its
submodules:

| Repository | What it says | What the assistant does with it |
|---|---|---|
| `ibek-support-infn` | For each driver, `<module>.install.yml` (git source = `organization` + `module`, version, libs, dbds, protocol files) and `<module>.ibek.support.yaml` (the entity models an IOC may instantiate) | find the driver for a device, its repository and version, its entities and required parameters |
| `ibek-templates` | Jinja2 templates that turn a beamline IOC entry (`template`, `devtype`, `iocprefix`, `devices`, `ps:`, `motor:`) into an ibek IOC YAML, and one test fixture per template | explain a template, start a new entry from a fixture, render and check it |
| `ibek-support`, `ibek-support-dls` | upstream support (asyn, motor, ADCore, modbus, …) and ibek's own `epics.*` entities | the same, for upstream types |
| `Dockerfile`, `Dockerfile.base` | which modules `ansible.sh` actually compiles into the image | tell "defined" apart from "available at pod start" |
| driver repositories (optional) | db templates, protocol files, README | show a driver's macros and records when writing its entity models |
| `docs/architecture.md` | how the image, ioc-chart, epik8s-chart and the beamlines fit together | `ioc_guide` |
| beamline repositories (optional) | the deploy value files: `iocDefaults` and the IOC entries | list, render and check a beamline's IOCs as deployed |

## The tools

They are MCP tools of the hub's server (`/mcp`), so Ask ARGUS uses them too. Like every MCP tool here they are
read-only. They find, explain, render and check. The scaffold returns text. Committing it, bumping submodules
and tagging an image stay with a person.

| Tool | Answers |
|---|---|
| `ioc_search` | Which module, entity model, template or example matches a vendor, device, driver or devtype |
| `ioc_get_module` | Where a driver comes from (git URL, version), how it is built, whether the image has it (and in which Dockerfile, or only commented out), its entity models, the templates that use it, and the indexed source |
| `ioc_get_entity_model` | One `module.entity` whole: typed parameters with defaults, st.cmd lines, databases and their macros, availability |
| `ioc_get_template` | One template: source, devtype branches, the variables it reads, the entity types it emits and whether the image has them, its examples |
| `ioc_get_example` | A worked entry: an ibek-templates fixture or a config kept in infn-epics-ioc |
| `ioc_render` | The entry rendered as the pod renders it, then checked as `ibek runtime generate` will check it |
| `ioc_validate` | The same check on an ibek IOC YAML written by hand |
| `ioc_scaffold_driver` | The `install.yml`, `ibek.support.yaml`, template and fixture for a new driver, with the Dockerfile line, rendered against each other |
| `ioc_list_beamline` | The beamlines in the catalogue, or one beamline's IOCs: template, devtype, prefix, how the pod starts them |
| `ioc_get_beamline_ioc` | One IOC as deployed: its entry, the iocDefaults it inherits, the values the pod receives, its render |
| `ioc_check_beamline` | Every enabled, templated IOC of a beamline rendered and checked: what its next sync would break |
| `ioc_guide` | The architecture document by section, the workflow, and which commit the catalogue was read from |

### What `ioc_render` reproduces

- **Template resolution** is `jnjrender --auto`'s. First it looks for a file `<template>.yaml.j2` anywhere under
  the templates. If there is none, it takes a directory of that name and renders every `.j2` in it. A
  directory with several YAML templates is reported, because `ioc/start.sh` refuses a config holding more than
  one `*.yaml`. A name that matches nothing is the pod's exit code 7.
- **Jinja2 semantics** are jnjrender's: plain `Template`, and an undefined variable renders as nothing. Rendering
  runs in Jinja2's sandbox, because the values come from whoever is asking. Each variable that rendered as
  nothing is listed in `rendered_empty`, which is usually a key missing from the entry.
- **`iocname`** is injected by epik8s-chart at deploy time. When the entry has none, the render uses `name`
  (lower case) and says so. A pasted `epicsConfiguration.iocs` block holding one IOC is read as that IOC.
- **The check** finds:
  - an entity type that no support module defines, with the types its module does define;
  - a type that is defined but not compiled into the image;
  - a missing required parameter (one with no default);
  - an int, float, bool or enum value of the wrong kind;
  - a duplicate `id`;
  - an `object` reference to an id that nothing declares;
  - parameters that the model does not declare.

  Values that still hold `{{ … }}` are left for ibek to render.

### What a beamline's IOC receives

`ioc_get_beamline_ioc`, `ioc_check_beamline` and `ioc_render(…, beamline=…)` build the values the pod finds in
`/tmp/iocconfig.yaml`, in the same order as the charts:

1. **The value files are merged.** For a multi-source beamline (SPARC, BTF), the files are the `valueFiles`
   named in `deploy/templates/*.yaml`, in that order. Otherwise only `deploy/values.yaml` is read. Maps merge
   key by key, and anything else is replaced by the later file.
2. **`iocDefaults` is merged under the entry.** The key is `iocDefaults.<template>`, or `<devtype>` when there
   is no template. epik8s-chart merges with Sprig's `mustMergeOverwrite`. The entry wins, but an empty value
   in it (`false`, `0`, `""`, `null`, `[]`) does not replace a non-empty default. Every key this affects is
   reported under `ignored_by_merge`, because `autosync: false` under a default of `true` silently stays
   `true`.
3. **epik8s-chart injects** `beamline`, `iocname` (the name in lower case), `ioc_version` (when the beamline
   sets it and the IOC has no `image:`) and `nfsMounts`.
4. **ioc-chart's ConfigMap adds** `<mount>_dir: <mountPath>/<iocname>` for each NFS mount, or `config_dir` and
   `autosave_dir` when there are none (`data_dir` comes from the chart's volume settings and is not reproduced). It also adds `ioctop`, and each `iocparam` as a
   top-level `name: value`. Keys from steps 1 to 3 win over these.

How the pod starts an IOC follows ioc-chart's precedence:

- `host:` runs remotely through epik8s-run;
- `template:` renders through jnjrender;
- otherwise the pod uses the git config directory.

Only `template:` IOCs are rendered and checked; the others are listed as skipped.

### Retired modules and stale examples

A module whose `ansible.sh` line is commented out in a Dockerfile was taken out of the image on purpose. An
example is the TML motor driver (`technosoft`), which `technosoft-asyn` replaced. Such a module is reported
as **retired**, and an entity from it fails the check with a pointer to the template's other devtypes.

Each example is rendered once against the image:

- One that no longer renders clean is listed last by `ioc_search`.
- `ioc_get_example` gives such an example a warning and a `use_instead` list, closest working examples first
  (by the words they share in their names).
- `ioc_get_template` marks each of its examples `renders_clean`.

The TML examples were the first case. They have since been converted to `technosoft-asyn`, and the `tml`
branch has been removed from the motor template. In the current snapshot, the one example that does not
render clean is `vme-dante068-test`: its types exist only in the RTEMS image, which the catalogue does not
read.

Known limits:

- ioc-chart's own default values (`iocConfig`, `start`, …) also land in `/tmp/iocconfig.yaml`. They are not
  reproduced; templates do not read them.
- The check covers what the catalogue's Dockerfiles build. An entry with another `image:` (for example the
  RTEMS image) is checked against the runtime image, and the result says so.
- `templates/global/` is not appended.
- The beamline schema (`ioc.schema.json`) is shipped in the catalogue but is not enforced.

## The catalogue

`python -m app.ioc_engineer build` reads a checkout of infn-epics-ioc into one JSON document. The hub ships a
snapshot (`backend/app/ioc_engineer/data/catalog.json.gz`). `ARGUS_IOC_CATALOG` points it at another snapshot
without a release.

```bash
git clone --recurse-submodules https://github.com/infn-epics/infn-epics-ioc
cd argus-knowledge-hub/backend
python -m app.ioc_engineer build --repo ../../infn-epics-ioc --sources /tmp/ioc-sources
python -m app.ioc_engineer summary
```

`--beamline URL[@REF]` (repeatable, or a local path) reads a beamline repository's deploy value files. The
snapshot includes ELI-NP (`epik8s-eli`, public). SPARC and BTF live on INFN's GitLab, so add them from a build
that can reach it:
`--beamline https://baltig.infn.it/…/epik8-sparc.git --beamline https://baltig.infn.it/…/epik8s-btf.git`.

`--sources DIR` also clones each INFN driver at the version its install.yml names (`organization` + `module`)
and indexes its db templates (macros, record sample), protocol files (commands), startup scripts and README.
Repositories the build cannot reach are listed under `sources.failed`. The drivers on `baltig.infn.it`
(`lnf-da-control`) are public, so the CI build on GitHub indexes them too; a private one fails the image build
as well as the catalogue (`could not read Username`). Each catalogue records the commit of infn-epics-ioc and of every submodule it was read
from, so an answer can be traced back to its files.

A type that is defined in two collections is taken from the copy the image builds. Dockerfile.base builds the
upstream modules from `ibek-support-dls`, and Dockerfile builds INFN's from `ibek-support-infn`.

### Following the image's releases

infn-epics-ioc builds the catalogue in CI (`.github/workflows/ioc-catalog.yml`) with this builder. On every
`v*` tag it attaches the result to the release, so the catalogue describes the image that tag publishes. Point
the hub at the latest one:

```
ARGUS_IOC_CATALOG=https://github.com/infn-epics/infn-epics-ioc/releases/latest/download/ioc-catalog.json.gz
```

- **Refresh.** The hub re-reads a URL every `ARGUS_IOC_CATALOG_TTL` seconds (six hours by default).
- **Fallback.** It keeps the last copy it fetched (`ARGUS_IOC_CATALOG_CACHE`). When GitHub cannot be reached,
  it answers from that copy, or from the bundled snapshot if it has none, and says so under `problems`.
- **Version.** `ioc_guide` reports `loaded_from` and the commits.
- **Beamlines.** The repository variable `IOC_CATALOG_BEAMLINES` sets which beamlines the CI build reads. Its
  default is ELI-NP.

The bundled snapshot (`backend/app/ioc_engineer/data/catalog.json.gz`) is used when `ARGUS_IOC_CATALOG` is not
set. Rebuild it with the command above when you want a newer offline default.

## Workflow the assistant follows

1. **A device of a known type.** Run `ioc_search`, then `ioc_get_template`. Start from `ioc_get_example`, or
   from a similar IOC through `ioc_list_beamline`. Then run `ioc_render(values, beamline=…)` on the entry until
   it reports no errors. Add the entry under `epicsConfiguration.iocs`, or
   rely on `iocDefaults.<template>`. Commit, then sync the ArgoCD application.
2. **A driver with no template.** Read the entity models in `ioc_get_module`. Write the template, then check it
   with `ioc_render(values, template_source=…)`.
3. **A new driver.** Run `ioc_scaffold_driver`, then adapt its entity models to the driver's db templates and
   st.cmd. `ioc_get_module` on a similar driver shows the house style.
   1. Add `ansible.sh <folder>` to the Dockerfile.
   2. Run `tests/test_ioc_generate.sh`.
   3. Bump the submodules and tag a release.
4. **Before a new image or a template change.** Run `ioc_check_beamline` for each beamline in the catalogue.
5. **An IOC that does not start.** Render its entry. "Unknown entity type" usually means the module is not in
   the image's `ansible.sh` list. "Template not found" means the image is older than the template.
