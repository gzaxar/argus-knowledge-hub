---
title: IOC engineer
summary: Getting help with EPICS IOCs built with ibek: find a driver, write a beamline IOC entry, check it before deploying, start a new driver.
keywords: [ioc, epics, ibek, beamline check, iocdefaults, pull request, pr, github, ibek-templates, ibek-support, driver, support module, template, devtype, values.yaml, epik8s, beamline, st.cmd, container, image, infn-epics-ioc, render, validate, scaffold]
order: 180
---

Ask ARGUS (and any assistant connected to the hub's MCP server) knows the drivers and templates of the INFN
IOC image, `infn-epics-ioc`. It can explain them, write a beamline IOC entry with you and check that entry
before you deploy it. It never deploys anything: what it writes is for you to review and commit.

## Configure a device of a known type

1. Ask, for example, "how do I add a Pfeiffer TPG 366 gauge controller at 192.168.1.20 to SPARC?".
2. The assistant searches the catalogue and opens the template (here `pfeiffer-tpg`) and an example entry.
3. It proposes the IOC entry for `deploy/values.yaml` (`template`, `devtype`, `iocprefix`, `devices`, …) and
   renders it the way the IOC pod will. **Check that the render shows no errors.** Each error is something
   `ibek` would stop on at pod start.
4. Add the entry under `epicsConfiguration.iocs`, commit it, and sync the IOC's application in ArgoCD.

## Check an entry you wrote

Paste the IOC's block, the whole `name: {template: …}` mapping, and ask "will this start?". The answer
lists:

- **errors**: an entity type that is unknown or not compiled into the image, a missing or wrong parameter, or
  a reference to an object that does not exist;
- **rendered_empty**: the keys the template expected and did not find;
- **warnings**, such as a devtype that matches none of the template's branches.

## Check a whole beamline

Ask "will every ELI IOC still start?" before a new IOC image or a template change. The assistant renders
every enabled, templated IOC of the beamline as deployed, with its `iocDefaults` merged in. It lists the IOCs
that would fail and why. It also lists every value the chart's merge ignores: a `false`, `0` or empty value in
an entry never replaces a default from `iocDefaults`. Ask about one IOC ("show me vgcon01 as deployed") to see
its entry, its defaults and the values the pod receives.

The beamlines it knows are the ones its catalogue was built with. Ask "which beamlines do you know?" to see
them.

## Support new hardware

Ask for a new driver ("draft the ibek support for the XYZ controller, repository xyz-ioc, StreamDevice"). You
get these drafts:

- `<folder>.install.yml` and `<folder>.ibek.support.yaml` for ibek-support-infn;
- a template and a test fixture for ibek-templates;
- the line to add to the Dockerfile.

The drafts are rendered against each other. Adapt the parameters to the driver's db template macros, then:

1. Run the ibek-support-infn tests.
2. Bump the submodules in infn-epics-ioc.
3. Tag a release.

## Open a pull request

When the files are right, ask "open a pull request with them". The answer shows the pull request as a proposed
change, with its repository, title and files. Nothing leaves ARGUS until you apply it.

1. Check the files and the checks listed under the proposal.
2. Select it and choose **Apply**. You need the *approve* permission in the workspace. ARGUS opens a draft pull
   request that lists the checks and names you as the person who confirmed it.
3. Follow the link to the pull request. The repository's reviewers review it and merge it; ARGUS never merges.

A new driver is two pull requests: the support module on ibek-support-infn, then the template and its fixture
on ibek-templates. If the option is not offered, an administrator has not installed the GitHub credential
(docs/ioc-engineer.md).

## When an IOC does not start

Give the assistant the IOC's entry and the error from the pod log. "Template directory … not found" (exit 7)
means the image is older than the template. "Unknown entity type" means the driver is not in the image's
build list.

## What it knows, and from when

The catalogue is read from a commit of infn-epics-ioc and its submodules. Ask "which version of the IOC
catalogue do you have?" to see that commit. An image tagged later can hold drivers or templates that the
catalogue does not know yet.
