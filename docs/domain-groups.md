# Groups by e-mail domain

An installation that lets in several identity providers (INFN AAI, Google) gives the people of an organisation some
access without giving it to every account that can sign in: a role goes to a group whose domains are, say, `infn.it`
and `*.infn.it`. Whoever signs in with a verified address there is in the group; a Gmail account is not.

## The rule

- `Group.email_domains` (JSONB list; null for an ordinary group). `infn.it` matches that domain exactly,
  `*.infn.it` any of its subdomains and not the domain itself. Patterns are checked and lower-cased
  (`services/domain_groups.normalise`); a top-level domain alone (`*.it`) is refused.
- Only a **verified** address counts: `User.email_verified`, from the identity provider's `email_verified` claim at
  each sign-in (None when it sends none, and then the address does not count). An unverified address could be
  anybody's.
- **A provider that gives out a domain's addresses vouches for them.** INFN AAI's tokens say `email_verified: false`,
  but INFN AAI is where the INFN addresses come from. The chart's `api.oidc.emailDomains` (`OIDC_EMAIL_DOMAINS`, or
  `email_domains` in an `OIDC_EXTRA_PROVIDERS` entry) names the domains a provider is the authority for; an address
  there that this provider signs in counts as verified (`auth_oidc.vouches_for`). Production sets
  `["infn.it", "*.infn.it"]` for INFN AAI. The same address from another provider still needs that provider's
  `email_verified`; another domain's address from INFN AAI too. Invalid domains in the setting are ignored, never
  trusted. The flag is written at each sign-in, so it changes at a person's next one.
- A removed or inactive person never counts.

## Membership

Kept as `group_members` rows with `source = "domain"`, so everything that reads membership (permissions, site-wide
grants, access reviews, "who has access", notifications) sees it unchanged.

- At every sign-in, `domain_groups.sync_user` adds and removes that person's rows (`auth.get_identity`).
- When a group's domains change, `domain_groups.sync_group` brings all its rows up to date at once.
- A member by address cannot be removed by hand (409); people added by hand stay whatever the domains.

## API

`PUT /v1/groups/{uid}/domains` `{domains, confirm}`: only the installation's administrators, signed in (a domain
can let in many people at once), only on a local group. Without `confirm`, the preview: `would_be_in_it`,
`examples`, `unverified` (people who signed in with an address there that was not verified), the group's
`workspaces` and `site_grants`. With it, the rows are synced and the access log gets `group.domains_set`.

In the web: **Groups**, open a local group, **E-mail domains** (shown to the installation's administrators).

Tests: `backend/tests/test_user_removal_domain_groups.py`, `webapp/src/__tests__/user-removal-domains.test.tsx`.
