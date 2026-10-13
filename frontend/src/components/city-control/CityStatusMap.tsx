import { CITY_CONTROL_ROWS, type CityStatus } from "@/data/city-control-grid-data"
import { cn } from "@/lib/utils"

const MAP_CSS = `
.city-status-map {
  --map-background: oklch(0.991 0.005 230);
  --map-land: oklch(0.968 0.012 230);
  --map-border: oklch(0.92 0.025 245);
  --map-heading: oklch(0.29 0.07 260);
  --map-city: oklch(0.37 0.045 210);
  --map-online: oklch(0.69 0.145 158);
  --map-online-text: oklch(0.65 0.12 158);
  --map-degraded: oklch(0.77 0.17 65);
  --map-degraded-text: oklch(0.77 0.13 65);
  --map-offline: oklch(0.66 0.22 25);
  --map-legend: oklch(0.58 0.065 260);
  width: 100%;
  aspect-ratio: 648 / 438;
  margin: 0;
  border: 2px solid var(--map-border);
  border-radius: 7px;
  overflow: hidden;
  background: var(--map-background);
  font-family: Inter, Arial, Helvetica, sans-serif;
}
.city-status-map svg { display: block; width: 100%; height: 100%; }
.city-status-map text { letter-spacing: 0; }
.city-status-map .land { fill: var(--map-land); stroke: var(--map-border); stroke-width: 2; stroke-linejoin: round; }
.city-status-map .boundary { fill: none; stroke: var(--map-border); stroke-width: 2; stroke-linejoin: round; }
.city-status-map .heading { fill: var(--map-heading); font-size: 23px; font-weight: 700; }
.city-status-map .city { fill: var(--map-city); font-size: 16px; font-weight: 600; }
.city-status-map .major { fill: var(--map-heading); font-size: 17px; font-weight: 700; }
.city-status-map .status { font-size: 16px; }
.city-status-map .online { fill: var(--map-online); }
.city-status-map .online-label { fill: var(--map-online-text); }
.city-status-map .degraded { fill: var(--map-degraded); }
.city-status-map .degraded-label { fill: var(--map-degraded-text); }
.city-status-map .offline { fill: var(--map-offline); }
.city-status-map .legend { fill: var(--map-legend); font-size: 16px; }
.city-status-map .halo { opacity: .16; }
`

const OUTLINE =
  "M 60,207 L 69,199 68,190 80,185 92,186 100,180 108,185 119,178 128,179 136,170 151,168 157,160 167,157 165,146 170,139 166,132 170,117 177,108 187,102 198,104 205,101 218,103 229,110 238,106 242,96 253,90 264,93 276,87 279,77 279,68 289,58 299,55 307,50 316,52 321,57 328,52 338,52 344,61 355,66 365,66 371,72 382,68 394,68 400,60 407,60 409,53 417,54 422,50 433,57 433,70 440,76 452,78 458,84 460,95 469,101 482,98 493,106 497,116 507,108 520,104 530,98 539,101 544,114 552,122 559,134 556,145 561,158 553,164 550,175 538,176 532,170 521,176 509,175 500,181 488,175 478,181 467,183 456,183 441,176 433,181 429,193 414,202 411,216 405,223 406,229 398,237 382,235 373,230 363,235 359,248 350,258 340,261 334,271 337,285 332,296 327,303 318,302 308,314 307,329 298,337 297,346 287,357 275,355 267,358 255,358 246,361 239,357 226,365 220,372 212,377 201,372 193,374 185,367 177,373 168,368 158,373 155,390 144,397 132,401 119,391 108,398 102,397 100,411 92,417 83,417 77,411 66,412 58,404 54,393 50,381 52,371 60,360 59,349 66,338 63,330 69,319 57,314 58,307 52,302 58,290 70,287 80,277 91,271 99,262 96,250 101,243 91,233 78,232 64,226 59,215 Z"

const BOUNDARIES = [
  "M 237,107 L 232,124 238,142 232,151 238,170 231,184 234,194 220,199 210,208 196,203 189,204 184,195 172,194 169,180 156,170",
  "M 234,194 L 246,202 258,201 263,209 271,211 275,225 280,238 275,248 264,256 261,273 255,288 260,301 274,307 277,321 287,326 290,342 296,348",
  "M 99,263 L 110,273 123,272 134,266 146,266 154,256 166,251 179,240 188,228 201,216 211,206",
  "M 280,238 L 293,239 304,247 311,262 324,270 336,267",
  "M 397,120 L 407,137 397,149 391,161 382,170 371,173",
]

type MapCity = {
  id: string
  name: string
  x: number
  y: number
  tx: number
  ty: number
  anchor?: "start" | "end" | "middle"
  major?: boolean
}

const MAP_CITIES: MapCity[] = [
  { id: "peshawar", name: "Peshawar", x: 169, y: 177, tx: 149, ty: 159, anchor: "end", major: true },
  { id: "mardan", name: "Mardan", x: 233, y: 136, tx: 253, ty: 128 },
  { id: "nowshera", name: "Nowshera", x: 321, y: 171, tx: 341, ty: 162 },
  { id: "kohat", name: "Kohat", x: 162, y: 239, tx: 183, ty: 235 },
  { id: "di-khan", name: "DI Khan", x: 111, y: 306, tx: 131, ty: 304 },
  { id: "swat", name: "Swat", x: 371, y: 89, tx: 390, ty: 84 },
  { id: "abbottabad", name: "Abbottabad", x: 493, y: 154, tx: 512, ty: 146, major: true },
]

const LEGEND: CityStatus[] = ["Online", "Degraded", "Offline"]

type CityStatusMapProps = {
  className?: string
  tall?: boolean
}

function statusClass(status: CityStatus) {
  return status.toLowerCase()
}

export function CityStatusMap({ className, tall }: CityStatusMapProps) {
  const byId = Object.fromEntries(CITY_CONTROL_ROWS.map((c) => [c.id, c]))

  const cities = MAP_CITIES.map((city) => ({
    ...city,
    status: (byId[city.id]?.status ?? "Online") as CityStatus,
  }))

  const description = [
    cities
      .filter((c) => c.status === "Online")
      .map((c) => c.name)
      .join(", ") + " are online.",
    cities
      .filter((c) => c.status === "Degraded")
      .map((c) => c.name)
      .join(", ") + (cities.some((c) => c.status === "Degraded") ? " is degraded." : ""),
    cities
      .filter((c) => c.status === "Offline")
      .map((c) => c.name)
      .join(", ") + (cities.some((c) => c.status === "Offline") ? " is offline." : ""),
  ]
    .filter((s) => s && !s.startsWith(" are") && !s.startsWith(" is"))
    .join(" ")

  return (
    <div
      className={cn(
        "flex min-h-[300px] flex-col overflow-hidden rounded-[10px] border border-[#D9E6F5] bg-white shadow-[0_1px_2px_rgba(16,44,85,0.04)]",
        className
      )}
    >
      <div className="border-b border-[#D9E6F5] px-4 py-3">
        <h2 className="text-[15px] font-semibold text-[#102C55]">City Status Map</h2>
      </div>

      <div className={cn("flex flex-1 items-center justify-center p-3", tall ? "min-h-[420px]" : "min-h-[280px]")}>
        <figure className="city-status-map" aria-label="City Status Map">
          <style>{MAP_CSS}</style>
          <svg viewBox="0 0 648 438" role="img" aria-labelledby="map-title map-description">
            <title id="map-title">City Status Map</title>
            <desc id="map-description">{description}</desc>

            <text x={25} y={37} className="heading">
              City Status Map
            </text>

            <path d={OUTLINE} className="land" />
            {BOUNDARIES.map((d, i) => (
              <path key={`boundary-${i}`} d={d} className="boundary" />
            ))}

            {cities.map((city) => {
              const state = statusClass(city.status)
              return (
                <g key={city.id}>
                  <circle cx={city.x} cy={city.y} r={12} className={`${state} halo`} />
                  <circle cx={city.x} cy={city.y} r={8} className={state} />
                  <text
                    x={city.tx}
                    y={city.ty}
                    textAnchor={city.anchor || "start"}
                    className={`${city.major ? "major" : "city"}${state === "degraded" ? " degraded-label" : ""}`}
                  >
                    {city.name}
                  </text>
                  <text
                    x={city.tx + (city.name === "Swat" ? 6 : 0)}
                    y={city.ty + 24}
                    textAnchor={city.anchor || "start"}
                    className={`status ${state === "offline" ? "offline" : `${state}-label`}`}
                  >
                    {city.status}
                  </text>
                </g>
              )
            })}

            {LEGEND.map((label, i) => (
              <g key={label}>
                <circle cx={510} cy={311 + i * 34} r={8} className={statusClass(label)} />
                <text x={533} y={317 + i * 34} className="legend">
                  {label}
                </text>
              </g>
            ))}
          </svg>
        </figure>
      </div>
    </div>
  )
}

export default CityStatusMap
