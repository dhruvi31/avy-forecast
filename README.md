# Avalanche Forecast

A fully free avalanche forecasting pipeline using ERA5 weather data and the
SNOWPACK model, automated with GitHub Actions and displayed on GitHub Pages.

## How it works
1. **GitHub Actions** runs daily (free, scheduled) and:
   - Fetches ERA5-Land weather data for your slope locations
   - (Next steps) Converts it to SNOWPACK's `.smet` format
   - (Next steps) Runs SNOWPACK to simulate the snowpack
   - (Next steps) Parses results into `data/results.json`
2. **GitHub Pages** serves `site/index.html`, which reads `data/results.json`
   and displays the forecast.

## Setup checklist
- [ ] Add your real slope coordinates to `data/locations.json`
- [ ] Add CDS API