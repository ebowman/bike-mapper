## devon: count points per OSM highway class (snap <= 30 m)

| OSM highway class snapped to | all points | counted (not estimated) in last 10 y |
|---|---|---|
| motorway | 6 | 6 |
| trunk | 131 | 120 |
| primary | 179 | 153 |
| secondary | 37 | 37 |
| tertiary | 92 | 89 |
| unclassified | 236 | 231 |
| residential | 190 | 187 |
| trunk_link | 6 | 4 |
| primary_link | 1 | 0 |
| living_street | 1 | 1 |
| service | 6 | 5 |
| track | 5 | 4 |
| path | 4 | 4 |
| cycleway | 8 | 7 |
| footway | 12 | 11 |
| TOTAL | 914 | 859 |

Snapped 914/914; median snap 1.6 m.

## devon: km of road within 2 km of a count point

| count-point set | class | total km | km within 2 km | % within | % NOT within |
|---|---|---|---|---|---|
| any count point | tertiary | 1,472 | 992 | 67.4 | 32.6 |
| any count point | unclassified | 8,297 | 5,093 | 61.4 | 38.6 |
| any count point | tertiary+unclassified | 9,769 | 6,085 | 62.3 | 37.7 |
| any count point | secondary | 751 | 508 | 67.7 | 32.3 |
| any count point | residential | 3,019 | 2,923 | 96.8 | 3.2 |
| points counted (not estimated) in last 10 y | tertiary | 1,472 | 985 | 67.0 | 33.0 |
| points counted (not estimated) in last 10 y | unclassified | 8,297 | 5,020 | 60.5 | 39.5 |
| points counted (not estimated) in last 10 y | tertiary+unclassified | 9,769 | 6,006 | 61.5 | 38.5 |
| points counted (not estimated) in last 10 y | secondary | 751 | 503 | 66.9 | 33.1 |
| points counted (not estimated) in last 10 y | residential | 3,019 | 2,915 | 96.5 | 3.5 |
| counted-10y points on MCU (minor C/U) roads | tertiary | 1,472 | 879 | 59.7 | 40.3 |
| counted-10y points on MCU (minor C/U) roads | unclassified | 8,297 | 4,123 | 49.7 | 50.3 |
| counted-10y points on MCU (minor C/U) roads | tertiary+unclassified | 9,769 | 5,002 | 51.2 | 48.8 |
| counted-10y points on MCU (minor C/U) roads | secondary | 751 | 424 | 56.4 | 43.6 |
| counted-10y points on MCU (minor C/U) roads | residential | 3,019 | 2,805 | 92.9 | 7.1 |

DfT cat x snapped class (all points):

hw   cycleway  footway  living_street  motorway  path  primary  primary_link  residential  secondary  service  tertiary  track  trunk  trunk_link  unclassified
cat                                                                                                                                                            
MB          0        0              0         0     0        1             0            0         36        1         0      0      0           0             0
MCU         0        3              1         0     0        0             0          188          1        3        88      4      0           0           234
PA          8        9              0         0     4      178             1            2          0        2         4      1     91           3             2
TA          0        0              0         1     0        0             0            0          0        0         0      0     40           3             0
TM          0        0              0         5     0        0             0            0          0        0         0      0      0           0             0
