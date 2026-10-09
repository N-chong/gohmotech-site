# Onboarding mascot visuals

The 15 PNGs in `static/images/onboarding/` were extracted unchanged from the supplied `GoHMoTech_Blue_White_Goat_Stickers_FIXED.zip`. They are not generated or recreated artwork.

The existing step configuration in `dashboard/onboarding.py` adds only a `mascot` attribute. Welcome uses the clipboard, dashboards and farm controls use the laptop, inventory/listings/reservations/reports use the checklist, marketplace browsing uses the magnifier, monitoring/messages use information, notifications use attention, and the final step uses celebration. Navigation uses `point_auto`; the renderer chooses the supplied left/right image from the actual target position. Skip confirmation uses the fast-forward sticker. Other supplied poses are available for future visual assignments without adding steps.

`templates/onboarding/mascot_assets.html` resolves all image URLs through Django's static tag. It is a URL map, not fifteen image elements or downloads. The renderer uses one decorative, asynchronously decoded image node with an empty alt attribute, `aria-hidden`, and disabled pointer events. It changes the source only when the pose changes and uses normal static-file caching across pages.

The mascot is a separate sibling of the existing card. It never changes card dimensions, controls, spotlight targets, or scrolling. Desktop placement tries free space beside the card, then above or below it. Mobile uses a 90px image above or below the card. Any placement overlapping the card, highlighted area, or viewport edge is rejected; if no placement fits, the image is hidden for that step. Missing image files also leave the tutorial usable. The subtle fade is disabled for reduced-motion preferences.

No changes were made to role detection, authentication, database state, first-login behavior, skip/finish actions, step order, text, routes, or navigation controls. The existing scoped installer and asset verifier now include these PNGs; this visual change adds no migration.
