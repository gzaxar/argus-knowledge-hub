# Administration scopes

ARGUS distinguishes four responsibilities:

| Scope | Assignment | What it can manage |
| --- | --- | --- |
| Instance | `users.is_admin` | The installation, its sites and all workspace access. |
| Site | One or more site administrators on a workspace whose role is `site` | Access to the site workspace and every facility workspace currently at that site. Site placement and instance settings remain instance administration. |
| Workspace | One or more people or groups with the **Workspace administrator** or **Owner** role on that workspace | People and group role grants in that workspace. The Workspace administrator role includes read access and member management; Owner also controls workspace content. |
| Group | One or more administrators on a local group | Add and remove that group's members, even when it holds roles in several workspaces. Group administrators do not gain workspace access merely by administering the group. |

The **Access** page grants a role to a person or a group. A group's members inherit the union of that group's roles in each workspace. **Viewer**, **Reporter**, **Agent**, **Approver**, **Contributor**, and **Curator** are the standard general access levels; **Workspace administrator** manages access; **Owner** includes content and access administration. Several bindings can coexist. A site administrator may grant those roles in any facility currently at their site.

The **Groups** page names group administrators and manages local group members. Someone who manages *all* workspaces where a group has a role can also appoint its administrators or change its metadata. This prevents an administrator of only one workspace from silently changing access in another. A group's creator becomes its first group administrator. Older groups have no explicit group administrator until an eligible workspace or instance administrator assigns one. Directory groups remain read only: their membership must be changed in the directory.

**My groups** in Administration lets a group administrator manage a group without being a member of any of its workspaces. A site administrator appears on the site's Access page. Site assignments stop granting authority when a facility leaves that site, and removing a workspace's site role removes its site administrator assignments.

A local group can receive members before it receives its first workspace role. Those members gain no workspace access until an authorized instance, site or workspace administrator grants a role to the group.

Workspace archives include site and group administrator assignments with the access data. Personal and robot API tokens do not receive these delegated powers automatically; token scopes still restrict administration.

## Site-level groups and group access (issue #26)

**Status: first part implemented.** Site-owned groups (`groups.home_site_id`), site-wide group grants
(`site_group_role_bindings`), their resolution from each workspace's *current* site, the scope checks below, the
refusals when a site loses its role or a facility moves, the site-wide and inherited sections of the Access page,
and group scope on the Groups page are in place. Still to come: a preview of who gains or loses access before a
facility moves (today the move is refused while it would leave grants out of scope), the source of each right in
My permissions and access reviews, carrying a facility-only archive's inherited access as a site dependency, and
the Flutter app. The migration created no grant: existing access is unchanged.

### Two separate scopes

- **Group ownership** answers who governs membership. A local group has either installation scope (the existing default) or one home site (`groups.home_site_id`). A site-owned group has one UID and one member list; it is not copied into each facility. Existing local groups remain installation-scoped. Directory groups remain owned by their directory and cannot be converted into local site groups.
- **Grant scope** answers where members receive rights. A direct workspace grant continues to work as today. A new site-wide group grant names a site, a group and one role; it applies to the site workspace and every workspace whose *current* `site_id` is that site. An installation-scoped or directory group may also receive a site-wide grant without changing who owns its membership.
- Creating a site group, adding members, or connecting a facility to a site grants no rights by itself. A site-wide or direct role grant is always an explicit step.

For example, the local **LNF operations** group can be owned by the LNF site. Granting it **Reporter** at LNF gives its members Reporter rights in LNF, SPARC and BTF while those facility workspaces belong to LNF. Its membership is maintained once.

### Administration and limits

| Action | Who may do it |
| --- | --- |
| Create a site-owned local group; appoint its group administrators | An instance administrator or an administrator of that site. |
| Add or remove a local group's members | Its group administrators, an instance administrator, or an administrator authorized for every scope where the group has grants. Site administrators may manage a site-owned group while all its grants remain within their site. |
| Grant, change or revoke a site-wide group role | An instance administrator or an administrator of that site. A workspace administrator cannot change a site-wide grant. |
| Grant a group a direct role in one facility | An instance, site or workspace administrator of that facility, subject to the group's ownership scope. |
| Change a directory group's membership | The external directory; ARGUS administrators manage only its ARGUS grants. |

A site-owned group may receive direct workspace grants only in its home site or its current facilities. Cross-site use requires an explicit move or promotion to installation scope, with a preview of affected rights and approval by an instance administrator. Group administrators manage membership; that appointment alone grants neither site nor workspace administration.

In the first version, site-wide grants accept the built-in **Viewer, Reporter, Agent, Approver, Contributor and Curator** roles. **Workspace administrator** and **Owner** are excluded: broad administration is assigned through site administrators. Custom or package roles need an explicit later review of their permissions, especially restricted classes. A site-wide Curator grant affects content in every facility, so the preview must make that reach clear.

### How access is calculated

The effective permissions in a workspace are the union of its existing direct user and group grants, legacy memberships, site-administrator authority, and applicable site-wide group grants. The same group can have a direct role and a site-wide role; both apply. Current workspace defaults and restricted-class checks still run through the central permission and visibility services. An inactive group contributes no permissions.

Site-wide grants are resolved from the workspace's current `site_id` on each permission check. They are **not copied into each facility's `role_bindings` rows**. A newly attached facility inherits them immediately. A departing facility loses them immediately. Moving a facility must preview who gains or loses access and identify any direct grants to site-owned groups that would become out of scope; those direct grants must be removed or reconciled before the move. Removing a site's `site` role must require revoking or converting its site-wide grants first, so a later return to site status cannot revive hidden access.

Permissions only add today. The first version therefore has **no per-facility deny or exception** to a site-wide grant. A facility cannot locally reduce a site-wide role. If facilities need different rights, use separate groups or direct workspace grants instead of a broad site grant.

### Administration screens and API

- On a site's **Access** page, add **Site-wide group access**: choose an active group, choose a permitted role, preview the site and every affected facility, then grant or revoke. Show the number of people and workspaces affected.
- On a facility's **Access** page, show inherited grants separately from direct grants, with a **From site LNF** label and a link to the site's grant. Facility administrators can edit their direct grants but cannot remove an inherited grant there.
- On **Groups**, show **Installation** or the home site's name, its group administrators, its direct grants and its site-wide grants. The group creation form offers **This site** only to its site or instance administrators.
- In **My permissions**, the account view and access reviews, show the source of each effective role: direct person, direct group, site-wide group or site administrator. Record who changed membership, grants and site relationships in the audit trail.
- Add a site-grant API under `/v1/admin/sites/{site_id}/group-grants` (list, create, revoke), and extend local group creation and listing with `home_site_id`. Validate all scope and role restrictions on the server. Personal and robot tokens remain limited by their existing scopes.

### Migration, export and acceptance checks

Add nullable `groups.home_site_id` and a `site_group_role_bindings` table (`site_id`, `group_uid`, `role_id`, creator, time; unique by site/group/role). Existing groups and bindings remain installation-scoped and workspace-direct; the migration creates no site grants. Offer a separate preview to convert a local group to site ownership, rejecting external direct grants until an administrator resolves them.

A portable archive of a site and its facilities includes site-owned groups, members, administrators and site-wide grants. A facility-only archive reports inherited access as an external site dependency; importing it must not create a site-wide grant or duplicate the group silently. Directory groups are matched to the destination directory identity or require explicit mapping.

Acceptance tests must cover a new facility inheriting a grant, a facility leaving and losing it, an inactive group, direct and inherited grants combined, a site-owned group blocked from another site, a directory group's read-only membership, a workspace administrator unable to alter site-wide grants, a site-role removal preview, and a facility-only import that cannot broaden access.
