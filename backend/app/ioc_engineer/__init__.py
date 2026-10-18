"""The IOC engineer: what ARGUS knows about building containerised EPICS IOCs with ibek.

Every hardware IOC at INFN runs from one generic image (infn-epics-ioc). What turns that image into
a specific IOC is written down in two repositories, and nowhere else:

    ibek-support-infn   how each driver is built (<module>.install.yml: git source, version,
                        libs, dbds) and which entities an IOC may instantiate
                        (<module>.ibek.support.yaml: typed parameters, startup lines, databases)
    ibek-templates      Jinja2 templates that turn a beamline's IOC entry (template, devtype,
                        iocprefix, devices, ps:, motor:) into an ibek IOC YAML, with one test
                        fixture per template

Upstream support (ibek-support, ibek-support-dls) adds asyn, motor, ADCore, modbus and friends,
and the Dockerfiles say which modules are actually compiled into the image.

`catalog.build` reads a checkout of infn-epics-ioc (with its submodules) into one JSON catalogue,
optionally with the driver sources each install.yml points at. `tools` answers from it: find a
driver, read an entity model or a template, render a beamline entry the way the pod does and check
what ibek will make of it, and draft the files a new driver needs. Nothing here deploys anything:
the output is files for a person to review and commit.

    python -m app.ioc_engineer build --repo PATH [--sources DIR] [--out FILE]
"""
