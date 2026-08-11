# Judging a Part's provenance

There is no verified-publisher flag any more, and there is no maintainer-vetted
catalog behind it.

That flag lived on `users.is_verified_publisher`, and only an admin route could
set it — a route gated on an account role nothing in Kerf ever wrote, so no
node could set it and the Library's "Verified only" filter returned an empty
catalog on every install that ever ran it. It was also the wrong shape: a node
asserting that its own parts are trustworthy is not a signal. Whose parts you
trust is decided by whose feed you follow.

So the star badge, the sort key and the `author.is_verified_publisher` field on
Part rows are all gone. Do not look for them, and do not tell a user how to
become a verified publisher — there is nothing to become.

## What to judge a Part on instead

The metadata is the signal, and you can read all of it:

1. **An exact manufacturer part number.** A Part with a real MPN can be
   cross-checked; one named "motor driver" cannot.
2. **Distributor entries with a SKU and a URL.** Those are checkable links to a
   supplier's own catalogue.
3. **A datasheet URL.**
4. **Whether the numbers are self-consistent** — a package that matches the
   footprint, a current rating that matches the application.

If the user is explicitly asking for a part by manufacturer or MPN, use that
exactly. Otherwise search the Library for a match and prefer the better
documented one. If nothing fits, suggest creating one with `create_part` and
include the manufacturer's URL in the `distributors` array so the user can
check it before ordering.

Say plainly when a Part is thin on metadata and the user is building toward a
real BOM. That is more useful than any flag was.

## Pricing and stock are often empty, and that is not "unavailable"

An imported Part usually arrives with:

- `distributors[*].url` set;
- `distributors[*].sku` set;
- `distributors[*].price_usd` and `distributors[*].stock` **null**, because the
  import runs without distributor API credentials and the sweep has not run yet.

Do not tell the user a Part is unavailable because its price is missing. If
they need fresh pricing now, point them at
`POST /api/projects/<pid>/files/<fid>/distributors/refresh` — which works
provided the node owner has configured the matching distributor credentials
under `/api/admin/distributors`.

## Library ordering

`GET /api/library/parts` orders by `files.updated_at desc`, most recently
touched first. It used to sort verified publishers to the top; there is no
such sort key now, and no listing in Kerf re-ranks by who published something.
