# Rack survey from the phone

A guided survey of a rack with the ARGUS Field app (**Survey a rack** on the home screen): photograph the rack and
its units, take or correct what is read, review the whole rack, save. Backend `app/services/rack_census.py`,
API `/v1/rack-census`, app `mobile/app/lib/features/census/`.

## The steps

1. **The rack.** Photograph its front and, if useful, its rear. Either start from a rack already in ARGUS (found
   by name or key), or from a rack not recorded yet: what is read on its label (name, identifier) is proposed, and
   racks it may be — the same key or name, or the racks of the room said — are offered ("It is this one"). For a
   new rack the person says its name, height in units and room, and may choose its point on the room's floor plan;
   the point is used only once confirmed ("Is it here? — Yes, here"). Nothing is guessed about where it stands.
2. **Each unit.** Photograph it; photograph its label or nameplate apart when the front does not show it. What the
   vision model reads — type, name, manufacturer, model, the serial number of that very unit, its height and its
   lowest unit when they are written on it — comes back as **proposals**, each with where it was read (the quoted
   text), how sure (a percentage), and whether it was really seen. A label's reading wins for the identity fields.
   The product model catalogue proposes the height ("catalogue: Halberd R7 server is 2 U"). Nothing is used until
   the person taps **Use**, or types the value; a value that was not read is shown as *not read — type it*.
   Without a vision model nothing is proposed and everything is typed.
3. **Which record.** A unit is linked to a record already in ARGUS, made as a new one, or left out. Possible
   duplicates are shown first: the same serial number (strong), the same key read on it, the same name, a unit of the
   same model already in the rack (weak). Making a new record while a strong or medium one is listed needs the person
   to say *I checked: it is another unit*. Its position is chosen on the drawing of the rack (a tap on a unit number)
   or typed, front or rear.
4. **Review and save.** The review lists what is missing (a decision, a type or name for a new record, a lowest unit
   or height not read), what overlaps or sticks out of the rack (the rack service's own checks, with the units
   already mounted), and possible duplicates. **Save the rack** is offered only when nothing is listed. Saving
   makes the rack (and places it, with its confirmed point) and the new records through the same code as the forms,
   mounts every unit through the rack service — with `source = "census"` and, as evidence, the survey, the photos
   and where each value came from (`{"serial": {"source": "label", "confidence": 0.99}}`) — and keeps each photo on
   the record it shows.

A survey is kept on the server at every step (`rack_censuses`): **Left half-way** lists the open ones, to resume
on this phone or another. Leaving one (*abandoned*) changes nothing. Applying is refused whole while the review
finds anything.

## API

| | |
|---|---|
| `POST /v1/rack-census` `{rack_uid?, place_uid?}` | start |
| `GET /v1/rack-census` | the open surveys |
| `GET`, `DELETE /v1/rack-census/{uid}` | read; leave it |
| `POST /{uid}/photos` multipart `role` (rack_front, rack_rear, device, label), `item`, `file` | a photo and its reading |
| `PUT /{uid}/rack` `{existing}` or `{values: {name, key, units, place_uid, plan_uid, x, y, position_confirmed}}` | which rack |
| `PUT /{uid}/items/{item}` `{values, decision, asset_uid, duplicate_checked}` | a unit's values and record |
| `GET /{uid}/review`, `POST /{uid}/apply` | review; make it so (409 with what is missing) |

A value sent as `{"value": …, "source": "photo"|"label"|"catalogue", "confidence": …}` was taken from a proposal; a
plain value was typed (`source = "person"`).

## Export and import

Surveys themselves are not carried by a workspace bundle (work in progress on a phone); what a survey applied is:
the rack, the records, their mountings with their evidence, and the photos as attachments of the records.
