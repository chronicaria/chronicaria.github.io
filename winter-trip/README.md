# Italy, winter 2026–27

A static site for a twelve-night trip — Milan, Venice, Florence, Rome, 20 December 2026 to
2 January 2027.

**Live: <https://chronicaria.github.io/winter-trip/>**

Plain HTML, one stylesheet, one script. No build step, no dependencies, no framework. Published
straight from `main` by GitHub Pages — push and it deploys. To work on it locally, open
`index.html`, or serve the folder:

    python3 -m http.server 8811

## Files

    index.html          the trip           travel.html     flights & trains
    itinerary.html      fourteen days      stays.html      lodging & budget
    como.html           23 December        bookings.html   what to reserve, when
    alternatives.html   what we cut        food.html       eating & practical
    assets/style.css    the design system
    assets/app.js       theme, nav, ⌘K jump, scroll reveal

## Content

Every fact comes from the research notes in the Rome vault at `Rome/Italy trip/`. The site is a
presentation layer — when a note changes, the page changes with it. `BUILD-CONTRACT.md` records
the markup and daylight-band conventions the pages were built to.

## The daylight band

Late-December Italy gets about nine hours of light. Each day in the itinerary carries a bar from
06:00 to 24:00: gold where the sun is up, ink where it is not, with brackets marking the day's
first and last scheduled moments. It is the constraint the whole route was built around, so it
is the one thing the design repeats.

Set in Cormorant Garamond and Newsreader. Press ⌘K to jump anywhere.
