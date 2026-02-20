# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      251 |       40 |     84% |280, 282, 284, 290, 298, 300, 320, 333, 335, 337, 339, 343, 345, 347, 349, 351, 353, 355, 385, 392, 408, 410, 420-421, 425, 439, 448, 450, 458, 468, 480, 482, 501-506, 512, 542 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        4 |     92% |41, 45-46, 75 |
| src/news\_recap/ingestion/controllers.py                 |      154 |       12 |     92% |143, 172, 194, 218, 241, 261, 293, 302, 338-339, 377, 388 |
| src/news\_recap/ingestion/dedup/calibration.py           |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/ingestion/dedup/cluster.py               |       74 |        4 |     95% |20, 58, 62, 128 |
| src/news\_recap/ingestion/dedup/embedder.py              |       71 |       14 |     80% |27-30, 40, 58, 61, 83-86, 89-91, 118 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      161 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       39 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      483 |       59 |     88% |115, 144, 184, 209, 239, 255-260, 278, 307-317, 441, 464-466, 530-534, 602, 640, 746-748, 796, 827, 855, 878-881, 953-960, 1014-1034, 1255-1257, 1285, 1368 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       51 |        3 |     94% |     97-99 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      419 |      113 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 668-673, 677-680, 720, 725, 729, 748-749, 759, 767 |
| src/news\_recap/ingestion/storage/alembic\_runner.py     |       12 |        0 |    100% |           |
| src/news\_recap/ingestion/storage/common.py              |       36 |        8 |     78% |24-27, 33-36 |
| src/news\_recap/ingestion/storage/sqlmodel\_models.py    |      342 |        0 |    100% |           |
| src/news\_recap/main.py                                  |      282 |       10 |     96% |727, 743, 914, 1084, 1133, 1159, 1224, 1347, 1389, 1419 |
| src/news\_recap/orchestrator/backend/base.py             |       24 |        0 |    100% |           |
| src/news\_recap/orchestrator/backend/benchmark\_agent.py |       80 |       80 |      0% |     3-127 |
| src/news\_recap/orchestrator/backend/cli\_backend.py     |      141 |       26 |     82% |78-84, 140, 160, 173-174, 181, 201-202, 221, 223, 227, 230, 241-242, 244, 314-315, 318-323 |
| src/news\_recap/orchestrator/backend/echo\_agent.py      |       19 |        0 |    100% |           |
| src/news\_recap/orchestrator/contracts.py                |      112 |       16 |     86% |77, 95, 97, 99, 115, 120, 127, 129, 131, 133, 135, 170, 174, 185, 206-207 |
| src/news\_recap/orchestrator/controllers.py              |      308 |       28 |     91% |381, 414-417, 420-423, 431-434, 453, 484, 505, 582-585, 631-632, 640, 649, 671, 714, 730, 748 |
| src/news\_recap/orchestrator/failure\_classifier.py      |       42 |        2 |     95% |  100, 127 |
| src/news\_recap/orchestrator/intelligence.py             |      335 |       88 |     74% |168-178, 193-195, 237, 310-400, 407-418, 425-434, 437-487, 538-550, 555-568, 574-579, 637, 641-644, 646-658, 706, 735, 822 |
| src/news\_recap/orchestrator/metrics.py                  |      236 |       49 |     79% |42-44, 98-102, 128-131, 154-157, 162, 166-168, 227, 229, 231-233, 304-306, 333, 352, 382, 460, 468, 476, 485, 509-515, 539-543, 549, 557 |
| src/news\_recap/orchestrator/models.py                   |      292 |        0 |    100% |           |
| src/news\_recap/orchestrator/output\_fallback.py         |       89 |       16 |     82% |24, 34, 37, 55, 67, 76, 87, 90, 95, 98, 105, 107, 111, 115, 119, 127 |
| src/news\_recap/orchestrator/pricing.py                  |       51 |        5 |     90% |41, 76, 79, 84-85 |
| src/news\_recap/orchestrator/repair.py                   |       14 |        1 |     93% |        30 |
| src/news\_recap/orchestrator/repository.py               |      635 |      116 |     82% |214-215, 240, 271, 280, 302, 324-338, 358-359, 480, 606, 629, 697, 815, 830, 925, 928, 930, 1020, 1022, 1024, 1026, 1045, 1047, 1069, 1139, 1161, 1202-1207, 1237-1266, 1275-1284, 1414-1422, 1450-1467, 1488, 1491, 1546-1561, 1591-1592, 1594, 1603-1665, 1698, 1774, 1783, 1810, 1826, 1860-1869, 1895-1903, 1965, 2031-2032, 2084, 2102-2103, 2124-2125, 2130-2131, 2163, 2166 |
| src/news\_recap/orchestrator/routing.py                  |      104 |       16 |     85% |65, 83, 85, 123, 128, 153, 188, 190, 193, 195, 198, 200, 202, 204, 206, 235 |
| src/news\_recap/orchestrator/sanitization.py             |       16 |        1 |     94% |        52 |
| src/news\_recap/orchestrator/services.py                 |       49 |        0 |    100% |           |
| src/news\_recap/orchestrator/smoke.py                    |      111 |       41 |     63% |72-89, 92-105, 146-149, 156, 176-192, 208, 211, 220-223, 228, 230, 240-255, 262 |
| src/news\_recap/orchestrator/usage.py                    |       91 |        3 |     97% |137, 140-141 |
| src/news\_recap/orchestrator/validator.py                |       37 |        5 |     86% |49, 57, 65, 74, 89 |
| src/news\_recap/orchestrator/workdir.py                  |       42 |        0 |    100% |           |
| src/news\_recap/orchestrator/worker.py                   |      512 |       90 |     82% |150-151, 180-182, 216, 218, 233, 238, 243, 254-255, 274, 301-313, 329, 408, 420-435, 457, 459, 542-543, 546-558, 631, 634-653, 729-749, 789-791, 796-797, 803-807, 827, 829, 849, 851, 906, 1006, 1011, 1015, 1072, 1085, 1088, 1094, 1112, 1114, 1116, 1127, 1130, 1134, 1143, 1146, 1148, 1151-1152, 1158, 1168, 1171, 1173, 1189, 1215, 1222-1225, 1233, 1290, 1295 |
| **TOTAL**                                                | **5968** |  **889** | **85%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fandgineer%2Fnews-recap%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.