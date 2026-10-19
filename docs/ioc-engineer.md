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
read-only. They find, explain, render and check. The scaffold returns text. Ask ARGUS can turn the drafts into
a pull request once a person confirms it (*Opening a pull request*). Reviewing and merging it, bumping
submodules and tagging an image stay with people.

| Tool | Answers |
|---|---|
| `ioc_search` | Which module, entity model, template or example matches a vendor, device, driver or devtype |
| `ioc_get_module` | Where a driver comes from (git URL, version), how it is built, whether the image has it (and in which Dockerfile, or only commented out), its entity models, the templates that use it, and the indexed source |
| `ioc_get_entity_model` | One `module.entity` whole: typed parameters with defaults, st.cmd lines, databases and their macros, availability |
| `ioc_get_template` | One template: source, devtype branches, the variables it reads, the entity types it emits and whether the image has them, its examples |
| `ioc_get_example` | A worked entry: an ibek-templates fixture or a config kept in infn-epics-ioc |
| `ioc_render` | The entry rendered as the pod renders it, then checked as `ibek runtime generate` will check it |
| `ioc_validate` | The same check on an ibek IOC YAML written by hand |
| `ioc_ibekize_repo` | An existing IOC repository (makeBaseApp tree with an example `st.cmd`) read into its `install.yml`, `ibek.support.yaml`, template and fixture, rendered against each other, with a report of where each value came from |
| `ioc_scaffold_module` | A new support module for hardware with no EPICS support, from a description of the device, in ppt-modulator's layout: makeBaseApp tree, an asyn port driver (C++) or a StreamDevice protocol, SNL state programs, db templates, `st.cmd` and `st-sim.cmd`, a TCP simulator, and the ibek files rendered against each other |
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

## Ibekizing an existing repository

`ioc_ibekize_repo` takes one of two inputs:

- an https URL on an allowed host (`ARGUS_IOC_SOURCE_HOSTS`, by default `github.com`, `gitlab.com` and
  `baltig.infn.it`);
- the name of a module the catalogue knows; then its `install.yml` gives the URL and version.

It clones the repository shallow, without submodules or hooks, and reads it; nothing in it is run.

| From | It writes |
|---|---|
| `*App/src/Makefile` (`*_LIBS`, `*_DBD`, `PROD_IOC` / `LIBRARY_IOC`, make variables expanded), else `configure/RELEASE` | `install.yml`: `module`, `organization`, `version`, `libs` and `dbds`, without base or the IOC itself. A support library lists its own library and dbd. An example IOC built beside it (ppt-modulator's layout) adds what it links and the dbds it names; its own `<ioc>.dbd` is listed only when a dbd of the repository's own goes into it and is never installed. |
| `*.proto` files and `Db/Makefile` | `protocol_files`: `db/<file>` when the Db Makefile installs the file, else its path in the repository |
| the example `st.cmd`: port set-up (`drvAsynIPPortConfigure`, `drvAsynSerialPortConfigure`, `drvModbusAsynConfigure`, `modbusInterposeConfig`, `asynSetOption`, driver `*Config*` commands) | a `controller` entity. Its port is `name`, and the address becomes `IP`/`TCPPORT` (or `TTY`), with the example's values as defaults. Derived ports become `{{name}}_<port>`. Its `pre_init` lines are the set-up. |
| `dbLoadRecords` and `dbLoadTemplate` (pattern and key=value substitution files), with `epicsEnvSet` values expanded | one entity per db template, with one typed parameter per macro. The default is the template's `$(M=default)`, or else the value `st.cmd` gives when every load agrees. A macro naming one of the controller's ports becomes the `controller` object. |
| `dbpf`, `seq` and the other after-`iocInit` lines | the controller's `post_init` |

Boilerplate (`dbLoadDatabase`, `*_registerRecordDeviceDriver`, `cd`, `iocInit`, `dbl`, …) is dropped.

The template maps the beamline vocabulary onto the entities: `P` comes from `iocprefix`, `R` from the device
name, and each other macro from the device's key, else the IOC's, else the model's default. The fixture is the
IOC as its `st.cmd` starts it.

The report says what to review:

- `inferred`: each value and where it came from;
- `required_without_example`: parameters nobody set;
- `kept_verbatim`: `st.cmd` lines copied as written, such as vendor initialisation;
- notes: for example a macro naming different ports across loads, which becomes a `<MACRO>_PORT` suffix
  parameter.

`self_check` renders the fixture against the drafts. Run on the 42 INFN driver repositories the catalogue
indexes, all 42 drafts pass their self-check.

What it cannot know: whether a macro that looks numeric is an integer or a float (it follows the example), and
which `st.cmd` values are site-specific rather than defaults. The drafts then go to two pull requests
(*Opening a pull request*).

## Writing a new module

`ioc_scaffold_module` takes a description of the device (`spec`). Everything in it is checked before a file is
written. A description that fails comes back with every problem at once, and an example.

```yaml
name: acme-ps                 # the repository
app: acme                     # acmeApp, the acmeSupport library, the acme IOC
description: ACME 3 kW power supply
group: ps
driver: asyn                  # asyn: a C++ asynPortDriver; stream: a StreamDevice protocol
transport: ip                 # ip (ip, port) or serial (tty, baud)
ip: 192.168.1.50
port: 4001
terminator: CRLF              # CRLF, LF, CR or none
poll: 1.0                     # seconds between readback polls (stream: the nearest SCAN)
timeout: 1.0
parameters:
  - {name: Current, type: float, unit: A, prec: 3, read: "MEAS:CURR?", write: "CURR %f", limits: [0, 100]}
  - {name: Voltage, type: float, unit: V, read: "MEAS:VOLT?"}
  - {name: Output, type: bool, states: [Off, On], read: "OUTP?", write: "OUTP %d"}
  - {name: Mode, type: enum, states: [Local, Remote], read: "SYST:MODE?"}
  - {name: Ident, type: string, read: "*IDN?", sim: "ACME,PS3000,SIM,1.0"}
sequences:
  - name: AutoOn
    retry_delay: 5.0
    steps:
      - {set: Output, value: On, wait: Output, equals: On, timeout: 10}
      - {set: Current, value: 10, wait: Current, above: 9.5, timeout: 60}
```

A parameter's `type` is one of `float`, `int`, `bool`, `enum` or `string`. It may also have:

- `read`: a query with no conversion;
- `reply`: the reply format, by default `%f`, `%d` or `%s` for the type;
- `write`: a command with exactly one conversion;
- `ack`: the device's answer to a write;
- `unit`, `prec` and `limits` (`DRVL`/`DRVH`);
- `states`: two names for a `bool`, 2 to 16 for an `enum`;
- `sim`: the simulator's starting value.

Commands are printable ASCII. The terminator is added to them.

A step sets a parameter that has a write command, waits for one that has a read command, or both. It waits
with `equals`, `above` or `below`. A value may name one of the parameter's states.

What it writes, under `<name>/`:

| Directory | It writes |
|---|---|
| `Makefile`, `configure/` | the makeBaseApp top. `RELEASE` names asyn, StreamDevice and the sequencer at the image's paths; put local paths in `RELEASE.local`. |
| `<app>App/src/` | `<app>Support` (the driver and the state programs, with their registrars in `<app>Support.dbd`) and the `<app>` IOC that links it |
| `<app>App/src/<app>Driver.{h,cpp}` (asyn) | an `asynPortDriver`. It talks to an octet port (`<app>Configure(port, octetPort, pollPeriod, timeout)`). A thread queries each readback and sets the parameter, or raises a COMM alarm. A write sends the command and, if `ack` is given, compares the answer. |
| `<app>App/Db/<app>.proto` (stream) | `get_<name>` and `set_<name>`. A whole-line string reply is read with `%#s`. |
| `<app>App/Db/<app>.template` | `$(P):$(R):<name>_RB` (`I/O Intr`, or `$(SCAN)` with stream) and `$(P):$(R):<name>_SP` (autosaved). With asyn, also `$(P):$(R):Connected`. |
| `<app>App/src/<app><Seq>.st`, `<app>App/Db/<app><Seq>.template` | the state program (`option +r`) and its records: `:Start`, `:Abort`, `:State` (Idle, Running, Done, Failed, Aborted), `:Step`, `:Message`. Each step's command is sent again every `RETRY_DELAY` seconds until its condition holds. When the step's timeout passes, the program stops in Failed, with the value it last read. |
| `iocBoot/ioc<app>/` | `st.cmd` for the device and `st-sim.cmd` for the simulator |
| `sim/<app>_sim.py` | a TCP simulator. A query answers the stored value, a command changes it. |

Beside it, the ibek files:

- `install.yml`: libs `asyn`, `stream`, `seq` and `pv` as needed, then `<app>Support`; the dbds; the protocol file;
- the support definition: one `controller` entity. It has `IP`/`TCPPORT` (or `TTY`/`BAUD`), plus `POLL` and
  `TIMEOUT` with asyn, or `SCAN` with stream, and `RETRY_DELAY` when there are sequences. It loads every
  template, and its `post_init` starts the state programs;
- the template and a fixture.

The template and the fixture are rendered and validated against each other.

What ARGUS does not do is compile. The hub has no EPICS toolchain, and the answer says so. The generator was
checked against EPICS 7.0.8, asyn R4-45, sequencer 2.2.9 and StreamDevice 2.8.24:

- both drivers, with TCP and serial transport, compile without a warning;
- each IOC runs against its simulator. Readbacks and setpoints work, including an enum with an
  acknowledgement and whole-line strings. A sequence finishes, times out into Failed, and can be aborted;
- the `st.cmd` that `ibek runtime generate` (3.1.2) writes from the drafts runs two controllers.

`ioc_ibekize_repo` reads a generated module back into the same libs and dbds.

## Opening a pull request

The tools above write nothing. A person who wants the drafted files in a repository asks Ask ARGUS for a
pull request ("open a PR with the template and its fixture"). Two people approve the change before it is
merged:

1. **The person in Ask ARGUS.** The assistant can only *propose* the pull request, with the new content of each
   file. The proposal appears under the answer like the record changes it can propose, and nothing leaves
   ARGUS until the person applies it.
   - Only a signed-in person can apply it, not an API token.
   - They need the `approve` permission in the workspace.
   - The checks run again when they apply it, against the catalogue the hub has at that moment.
2. **The repository's reviewers.** ARGUS makes one commit on a new branch (`argus/<title>-<suffix>`) and opens
   a draft pull request. ARGUS never merges.
   - The pull request lists the checks that ran and names the person who confirmed it.
   - It also says what the checks cannot see: addresses, ports, channels and axis ids.

**Checks at proposal time.** A proposal that fails one of them is refused, and the reason goes back to the
model so it can fix the files:

- the repository is in `ARGUS_IOC_PR_REPOS` (by default `infn-epics/ibek-support-infn`,
  `infn-epics/ibek-templates` and `infn-epics/infn-epics-ioc`);
- paths stay inside the repository and out of `.github/`, so CI is not the assistant's to change;
- at most 20 files of 200 kB each;
- YAML parses;
- an `*.ibek.support.yaml` declares its `module` and `entity_models`, and an `*.install.yml` its `module`;
- every ibek-templates fixture (`tests/*.yaml`) and every infn-epics-ioc `*-config.yaml` in the change renders
  and passes the same check as `ioc_render`.

The fixture is rendered against the template in the same change if there is one, otherwise the image's. Entity
models in the change, and in pull requests proposed earlier in the same conversation, count as known. So a new
driver is two pull requests (`ibek-support-infn`, then `ibek-templates`), and the template's fixture already
checks against the driver proposed just before it. A template without a fixture in the change is noted in the
pull request.

**Configuration.** The feature is off unless an administrator installs a credential:

| Variable | Meaning |
|---|---|
| `ARGUS_GITHUB_TOKEN` | A fine-grained token, or a GitHub App's, with *Contents* and *Pull requests* read and write on the allowed repositories only. When it is absent, the assistant is not offered the tool. In the chart it is the key `ioc-github-token` of `existingSecret` (k8s/README.md). |
| `ARGUS_IOC_PR_REPOS` | Comma-separated `owner/name` list; the chart's `iocEngineer.pullRequests.repositories`. |
| `ARGUS_IOC_PR_DRAFT` | `true` (default) opens drafts. |
| `ARGUS_GITHUB_API` | For GitHub Enterprise; default `https://api.github.com`. |

The external MCP tools stay read-only. Only Ask ARGUS, where a person confirms, can propose a pull request.

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
