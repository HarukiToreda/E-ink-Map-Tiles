# Location search and boundary providers

Location search answers “where should the map look?” Boundary resolution answers “which exact geometry should become export coverage?” Keeping those operations separate makes search fast and avoids sending an expensive boundary request for every result.

Provider information in this document was reviewed on 2026-10-11. Public-service rules can change; re-check the linked primary documentation before a hosted release.

## Search flow

```mermaid
sequenceDiagram
    actor User
    participant App
    participant N as Nominatim
    participant P as Photon

    User->>App: Submit a query
    App->>N: Forward search, limit 5, address details
    alt Nominatim returns valid results
        N-->>App: Points, bounding boxes, OSM IDs
    else Nominatim returns a valid empty result
        App->>P: Fuzzy forward search
        P-->>App: GeoJSON feature results
    else Nominatim request fails
        N-->>App: HTTP or network error
        App-->>User: Visible search error
    end
    App-->>User: Result rows with View and Add area
```

Search does not request polygon geometry. Even if a search response happens to contain geometry, the normalized `SearchResult` deliberately sets `geojson` to `null` until the user chooses **Add area**.

Stale requests are ignored using a monotonically increasing request ID. Changing the query invalidates the current request and dismisses the dropdown. It does not currently abort the provider request at the network layer.

## Search providers

| Provider                | Endpoint used                        | Role                                                                 | Timeout | Important behavior                                                |
| ----------------------- | ------------------------------------ | -------------------------------------------------------------------- | ------: | ----------------------------------------------------------------- |
| OpenStreetMap Nominatim | `nominatim.openstreetmap.org/search` | Primary worldwide forward search                                     |    12 s | Exact query submission only; no autocomplete requests             |
| Photon public demo      | `photon.komoot.io/api/`              | Fuzzy fallback when Nominatim successfully returns no usable results |    12 s | Builds readable names from name, city, county, state, and country |

The Nominatim public service currently requires light, user-triggered use, visible attribution, an identifying Referer/User-Agent, and no client-side autocomplete. Its stated absolute maximum is one request per second, and systematic/bulk queries are forbidden. See the [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/).

Photon describes `photon.komoot.io` as a public demo service suitable for reasonable use, without availability guarantees; extensive use may be throttled or blocked. See the [Photon project README](https://github.com/komoot/photon/blob/master/README.md) and [API documentation](https://github.com/komoot/photon/blob/master/docs/api-v1.md).

The present local application model—one request only after a user submits a search—is intentionally conservative. A broadly hosted deployment must review aggregate traffic and should make endpoints configurable or operate its own service.

## Result normalization

```mermaid
flowchart LR
    Raw[Provider response: unknown] --> Guard[Runtime shape checks]
    Guard --> Valid{Finite lat/lon<br/>within world bounds?}
    Valid -->|No| Drop[Discard item]
    Valid -->|Yes| Normalize[Normalize name, category,<br/>bbox, country, postcode, OSM identity]
    Normalize --> Result[SearchResult with geojson = null]
```

External JSON remains `unknown` until checked. Malformed items are discarded instead of being allowed into application state. Bounding boxes must have four finite coordinates, ordered south-to-north, within valid latitude/longitude ranges.

## View versus Add area

```mermaid
flowchart TD
    Result[Search result] --> Action{User action}
    Action -->|View| Reveal[Reveal map]
    Reveal --> Center[Center and fit result bbox]
    Center --> NoSelection[No export coverage added]
    Action -->|Add area| Resolve[Resolve detailed boundary]
    Resolve --> Selection[Create or upgrade selection]
    Selection --> Center2[Center and fit selected area]
```

This distinction is an invariant. Do not make search submission or **View** create a selection as a convenience; it would make export coverage surprising.

## Boundary-resolution flow

```mermaid
flowchart TD
    Add[Add area] --> Existing{Result already has geometry?}
    Existing -->|Yes| Use[Use it]
    Existing -->|No| OSM{OSM way or relation ID?}
    OSM -->|Yes| Object[Overpass object geometry]
    Object --> ObjectFound{Polygon found?}
    ObjectFound -->|Yes| Use
    ObjectFound -->|No| US{US postcode?}
    OSM -->|No| US
    US -->|Yes| Tiger[Census TIGERweb ZCTA]
    Tiger --> TigerFound{Polygon found?}
    TigerFound -->|Yes| Use
    TigerFound -->|No| Postal{Postcode + bbox?}
    US -->|No| Postal
    Postal -->|Yes| OverpassPostal[Overpass postal_code/ref query]
    OverpassPostal --> PostalFound{Polygon found?}
    PostalFound -->|Yes| Use
    PostalFound -->|No| BBox[Use approximate bounding rectangle]
    Postal -->|No| BBox
    Use --> Exact[Exact polygon/multipolygon selection]
    BBox --> Approx[Approximate rectangular selection]
```

The order is intentionally worldwide-first. The U.S. Census provider is a fallback for a U.S. postcode, not a default preference for U.S. results.

## Boundary providers

| Provider                             | When called                                                                      | Output                                          | Scope and caveat                                                                            |
| ------------------------------------ | -------------------------------------------------------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------- |
| OpenStreetMap Overpass               | User adds a result with a way/relation identity                                  | Way polygon or stitched relation multipolygon   | Worldwide, best effort; relation member geometry can be incomplete or complex               |
| Census TIGERweb                      | OSM object resolution failed and the selected item is a five-digit U.S. postcode | ZCTA polygon/multipolygon                       | United States only; ZCTAs approximate postal delivery areas and are not USPS ZIP boundaries |
| OpenStreetMap Overpass postal search | Earlier resolution failed and a postcode plus bbox are available                 | Postal boundary matching `postal_code` or `ref` | Worldwide where OSM has a mapped postal boundary                                            |
| Search-result bbox                   | No detailed geometry was found                                                   | Rectangle                                       | Always marked approximate by `exact: false`                                                 |

TIGERweb provides REST services intended for GIS and custom web applications. Its datasets and service organization evolve by release; see the [TIGERweb overview](https://tigerweb.geo.census.gov/) and [REST service directory](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb).

Overpass requests are made only after an explicit selection. Do not move them back into search-result generation. A query-per-result pattern is slow for users and abusive toward shared public infrastructure.

## Overpass geometry construction

```mermaid
flowchart LR
    Elements[Overpass elements] --> Kind{Way or relation?}
    Kind -->|Closed way| Polygon[One polygon ring]
    Kind -->|Relation| Members[Outer and inner way fragments]
    Members --> Stitch[Stitch matching endpoints]
    Stitch --> Holes[Assign inner rings to containing outers]
    Holes --> Count{Outer polygon count}
    Count -->|One| P[Polygon]
    Count -->|Many| MP[MultiPolygon]
```

The stitcher is intentionally modest. It joins exact endpoint matches and uses point-in-ring containment for holes. If geometry cannot be constructed, resolution falls through rather than pretending the shape is exact.

## Boundary request cache

Resolved boundary work is cached in memory by OSM identity, country, postcode, and bbox. The cache stores at most 64 in-flight/completed promises.

```mermaid
flowchart TD
    Request[Boundary request] --> Key[Build identity key]
    Key --> Cache{Promise cached?}
    Cache -->|Yes| Share[Share in-flight/completed promise]
    Cache -->|No| Resolve[Run provider chain]
    Resolve --> Success{Resolved?}
    Success -->|Yes| Retain[Retain bounded cache entry]
    Success -->|No| Remove[Remove entry so retry is possible]
```

Failures are not cached for the whole session. A timeout or temporary outage should be retryable when the user chooses the result again.

## Map and terrain sources

Location providers are separate from map-tile providers.

```mermaid
flowchart LR
    Search[Search/boundary providers] --> Geometry[Navigation and selection geometry]
    Tiles[OpenFreeMap or USGS] --> Pixels[Base map pixels]
    Terrain[Mapzen Terrarium] --> Pixels
    Geometry -. never supplies base-map pixels .-> Pixels
```

| Source             | Current endpoint                                                  | Primary documentation                                                                                                                                   |
| ------------------ | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OpenFreeMap vector | `tiles.openfreemap.org/planet/latest/{z}/{x}/{y}.pbf`             | [OpenFreeMap Quick Start](https://openfreemap.org/quick_start/), [project attribution](https://github.com/hyperknot/openfreemap#attribution)            |
| USGS topo raster   | `basemap.nationalmap.gov/.../USGSTopo/MapServer/tile/{z}/{y}/{x}` | [USGSTopo service directory](https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer)                                                   |
| Mapzen terrain     | `s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png` | [Terrain Tiles dataset](https://registry.opendata.aws/terrain-tiles/), [Terrarium format](https://github.com/tilezen/joerd/blob/master/docs/formats.md) |

Attribution is centralized in `mapConfig.ts` and reused by the footer and exported artifacts. Adding a source requires adding its accurate attribution at the same time.

## Privacy and deployment guidance

- Search text is sent to the configured third-party geocoder.
- Selected OSM IDs, postcodes, and bounding boxes may be sent to Overpass or TIGERweb.
- Map coordinates are sent to tile and terrain providers as URL paths.
- No project session, marker label, or imported GeoJSON is intentionally uploaded by the application.
- The application has no proxy that can enforce global rate limits across users.

```mermaid
flowchart TD
    Deployment[Deployment model] --> Local{Local/small manual use?}
    Local -->|Yes| Public[Public endpoints may be acceptable<br/>after policy review]
    Local -->|No| Hosted[Hosted or high-volume use]
    Hosted --> Control[Use configurable/contracted/self-hosted providers]
    Control --> Limits[Add aggregate rate limits, caching, monitoring]
```

## Adding or replacing a provider

1. Document the user need and why existing providers cannot satisfy it.
2. Confirm browser CORS support, acceptable-use rules, attribution, privacy implications, and expected availability.
3. Keep provider response JSON at an `unknown` boundary and normalize it into existing domain types.
4. Do not expose raw provider objects to React components.
5. Preserve the distinction between search and boundary resolution.
6. Make timeouts and fallback order explicit.
7. Add mocked tests for success, empty results, malformed responses, HTTP failure, timeout/fallback, and geographic restrictions.
8. Update source attribution and this document.
