# Benchmark report

Real scanner (`hccb.detect.scan_image`) on synthetically distorted renderings. n = 30 random IDs per condition and mode, seed 1234, canvas 640 px, tag 50 % of width unless stated. Runtime 205.86 s.

| condition | MS Tag (RE) | Experimental v1 | wrong IDs | median ms |
|---|---|---|---|---|
| clean | 30/30 | 30/30 | 0 | 47 |
| rot 0° | 30/30 | 30/30 | 0 | 47 |
| rot 90° | 30/30 | 30/30 | 0 | 46 |
| rot 180° | 30/30 | 30/30 | 0 | 47 |
| rot 270° | 30/30 | 30/30 | 0 | 46 |
| rot 23° | 30/30 | 30/30 | 0 | 47 |
| small (12% of frame) | 30/30 | 30/30 | 0 | 35 |
| large (90% of frame) | 30/30 | 30/30 | 0 | 63 |
| perspective 0.25 | 30/30 | 30/30 | 0 | 45 |
| perspective 0.45 | 30/30 | 30/30 | 0 | 53 |
| blur σ=2 | 30/30 | 30/30 | 0 | 54 |
| blur σ=4 | 30/30 | 30/30 | 0 | 47 |
| motion blur 12px | 30/30 | 30/30 | 0 | 45 |
| dark (-0.35) | 30/30 | 30/30 | 0 | 81 |
| bright (+0.3) | 30/30 | 30/30 | 0 | 55 |
| low contrast 0.5 | 30/30 | 30/30 | 0 | 73 |
| desaturated 0.4 | 30/30 | 30/30 | 0 | 49 |
| hue +25° | 30/30 | 30/30 | 0 | 52 |
| hue +60° | 30/30 | 30/30 | 0 | 52 |
| warm cast (γ 1.6) | 30/30 | 30/30 | 0 | 51 |
| JPEG q=30 | 30/30 | 30/30 | 0 | 50 |
| JPEG q=10 | 30/30 | 30/30 | 0 | 50 |
| noise σ=0.06 | 30/30 | 30/30 | 0 | 61 |
| noise σ=0.15 | 30/30 | 30/30 | 0 | 57 |
| occlusion 3% | 30/30 | 30/30 | 0 | 47 |
| occlusion 8% | 30/30 | 30/30 | 0 | 46 |
| clutter background | 30/30 | 30/30 | 0 | 106 |
| texture background | 30/30 | 30/30 | 0 | 146 |
| tiny (6% of frame) | 28/30 | 26/30 | 0 | 54 |
| perspective 0.65 | 30/30 | 30/30 | 0 | 40 |
| blur σ=7 | 30/30 | 30/30 | 0 | 47 |
| contrast 0.2 | 30/30 | 30/30 | 0 | 73 |
| hue +120° | 30/30 | 30/30 | 0 | 46 |
| greyscale (sat 0.05) | 30/30 | 30/30 | 0 | 50 |
| JPEG q=5 | 30/30 | 30/30 | 0 | 51 |
| noise σ=0.3 | 30/30 | 30/30 | 0 | 103 |
| occlusion 12% | 1/30 | 4/30 | 0 | 173 |
| occlusion 20% | 0/30 | 0/30 | 0 | 174 |
| combined (rot+persp+blur+jpeg) | 30/30 | 30/30 | 0 | 59 |

False-positive trial: **0 decodes in 200 tag-free images** (random clutter/texture/gradient backgrounds; every 5th contains a random triangle mosaic in a valid frame).
