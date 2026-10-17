import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveBrowserLocationBoundary, searchBrowserLocations } from "./search";

describe("browser boundary resolution", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("ignores malformed provider results", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify([null, "bad", { lat: 1 }]))),
    );
    await expect(searchBrowserLocations("example")).resolves.toEqual({ results: [] });
  });

  it("upgrades a U.S. postcode bounding box to its Census ZCTA polygon", async () => {
    const polygon = {
      type: "Polygon",
      coordinates: [
        [
          [-82.4, 36.3],
          [-82.2, 36.3],
          [-82.3, 36.5],
          [-82.4, 36.3],
        ],
      ],
    };
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              display_name: "37601, Johnson City, Tennessee, United States",
              lat: "36.33",
              lon: "-82.34",
              boundingbox: ["36.2", "36.5", "-82.5", "-82.1"],
              type: "postcode",
              address: { postcode: "37601", country_code: "us" },
              geojson: { type: "Point", coordinates: [-82.34, 36.33] },
            },
          ]),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ features: [{ geometry: polygon }] }), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetch);

    const searchResult = (await searchBrowserLocations("37601")).results[0];
    expect(searchResult.geojson).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
    const result = await resolveBrowserLocationBoundary(searchResult);
    expect(result.geojson).toEqual(polygon);
    expect(result.boundary_label).toBe("Census ZCTA boundary");
    expect(result.geometry_source).toBe("U.S. Census Bureau TIGERweb");
    expect(String(fetch.mock.calls[1][0])).toContain("ZCTA5%3D%2737601%27");
  });

  it("returns Nominatim search results without requesting geometry", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            display_name: "Example",
            lat: "2",
            lon: "1",
            boundingbox: ["1", "2", "1", "2"],
            type: "administrative",
            osm_type: "relation",
            osm_id: 7,
            address: { country_code: "de" },
          },
        ]),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetch);

    const result = (await searchBrowserLocations("Example")).results[0];
    expect(result.geojson).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(String(fetch.mock.calls[0][0])).not.toContain("polygon_geojson");
  });

  it("resolves a non-U.S. postal boundary from OpenStreetMap Overpass", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              display_name: "10117 Berlin, Germany",
              lat: "52.51",
              lon: "13.38",
              boundingbox: ["52.49", "52.53", "13.35", "13.41"],
              type: "postcode",
              address: { postcode: "10117", country_code: "de" },
              geojson: { type: "Point", coordinates: [13.38, 52.51] },
            },
          ]),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            elements: [
              {
                type: "way",
                geometry: [
                  { lon: 13.35, lat: 52.49 },
                  { lon: 13.41, lat: 52.49 },
                  { lon: 13.41, lat: 52.53 },
                  { lon: 13.35, lat: 52.49 },
                ],
              },
            ],
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetch);

    const searchResult = (await searchBrowserLocations("10117")).results[0];
    expect(fetch).toHaveBeenCalledTimes(1);
    const result = await resolveBrowserLocationBoundary(searchResult);
    expect(result.geojson?.type).toBe("Polygon");
    expect(result.boundary_label).toBe("Postal boundary");
    expect(result.geometry_source).toBe("OpenStreetMap Overpass");
    expect(String(fetch.mock.calls[1][0])).toContain(
      "https://overpass-api.de/api/interpreter?data=",
    );
    expect(String(fetch.mock.calls[1][0])).toContain("postal_code");
  });

  it("recovers worldwide region geometry from its OSM relation", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              display_name: "Example Region",
              lat: "2",
              lon: "1",
              boundingbox: ["1", "3", "0", "2"],
              type: "administrative",
              osm_type: "relation",
              osm_id: 42,
              address: { country_code: "xx" },
            },
          ]),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            elements: [
              {
                type: "relation",
                members: [
                  {
                    type: "way",
                    role: "outer",
                    geometry: [
                      { lon: 0, lat: 1 },
                      { lon: 2, lat: 1 },
                      { lon: 2, lat: 3 },
                    ],
                  },
                  {
                    type: "way",
                    role: "outer",
                    geometry: [
                      { lon: 0, lat: 1 },
                      { lon: 2, lat: 3 },
                    ],
                  },
                ],
              },
            ],
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetch);

    const searchResult = (await searchBrowserLocations("Example Region")).results[0];
    expect(fetch).toHaveBeenCalledTimes(1);
    const result = await resolveBrowserLocationBoundary(searchResult);
    expect(result.geojson?.type).toBe("Polygon");
    expect(result.boundary_label).toBe("OpenStreetMap boundary");
    expect(String(fetch.mock.calls[1][0])).toContain("relation%2842%29");
  });

  it("uses fuzzy OSM search immediately and resolves only the selected result's boundary", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("[]", { status: 200 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            features: [
              {
                type: "Feature",
                properties: {
                  osm_type: "R",
                  osm_id: 197297,
                  osm_key: "place",
                  type: "city",
                  name: "Johnson City",
                  county: "Washington",
                  state: "Tennessee",
                  country: "United States",
                  countrycode: "US",
                  extent: [-82.52, 36.43, -82.29, 36.25],
                },
                geometry: { type: "Point", coordinates: [-82.35, 36.32] },
              },
            ],
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            elements: [
              {
                type: "way",
                geometry: [
                  { lon: -82.52, lat: 36.25 },
                  { lon: -82.29, lat: 36.25 },
                  { lon: -82.29, lat: 36.43 },
                  { lon: -82.52, lat: 36.25 },
                ],
              },
            ],
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetch);

    const searchResult = (await searchBrowserLocations("johnsoncity")).results[0];
    expect(searchResult.display_name).toBe("Johnson City, Washington, Tennessee, United States");
    expect(searchResult.bbox).toEqual({ west: -82.52, south: 36.25, east: -82.29, north: 36.43 });
    expect(searchResult.geojson).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][0]).toContain("photon.komoot.io");
    const result = await resolveBrowserLocationBoundary(searchResult);
    expect(result.geojson?.type).toBe("Polygon");
    expect(String(fetch.mock.calls[2][0])).toContain("relation%28197297%29");
  });
});
