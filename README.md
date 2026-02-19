# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      166 |       20 |     88% |273, 280, 296, 298, 308-309, 313, 327, 336, 338, 346, 356, 368, 370, 389-394 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        4 |     92% |41, 45-46, 75 |
| src/news\_recap/ingestion/controllers.py                 |      154 |       12 |     92% |143, 172, 194, 218, 241, 261, 293, 302, 338-339, 376, 387 |
| src/news\_recap/ingestion/dedup/calibration.py           |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/ingestion/dedup/cluster.py               |       74 |        4 |     95% |20, 58, 62, 128 |
| src/news\_recap/ingestion/dedup/embedder.py              |       71 |       14 |     80% |27-30, 40, 58, 61, 83-86, 89-91, 118 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      161 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       39 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      493 |       59 |     88% |104, 133, 173, 198, 228, 244-249, 267, 296-306, 430, 453-455, 519-523, 591, 629, 735-737, 785, 816, 844, 867-870, 942-949, 1003-1023, 1244-1246, 1274, 1363 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       51 |        3 |     94% |     97-99 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      419 |      113 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 668-673, 677-680, 720, 725, 729, 748-749, 759, 767 |
| src/news\_recap/ingestion/storage/alembic\_runner.py     |       12 |        0 |    100% |           |
| src/news\_recap/ingestion/storage/common.py              |       15 |        8 |     47% |18-21, 27-30 |
| src/news\_recap/ingestion/storage/sqlmodel\_models.py    |      342 |        0 |    100% |           |
| src/news\_recap/main.py                                  |      279 |       10 |     96% |699, 715, 886, 1056, 1105, 1131, 1196, 1319, 1361, 1391 |
| src/news\_recap/orchestrator/backend/base.py             |       21 |        0 |    100% |           |
| src/news\_recap/orchestrator/backend/benchmark\_agent.py |       80 |       38 |     52% |39-40, 43-50, 63-67, 70-71, 101-107, 111-112, 116-127 |
| src/news\_recap/orchestrator/backend/cli\_backend.py     |       56 |       12 |     79% |71, 82-83, 99, 103-115, 123-124, 131 |
| src/news\_recap/orchestrator/backend/echo\_agent.py      |       19 |        0 |    100% |           |
| src/news\_recap/orchestrator/contracts.py                |      112 |       16 |     86% |77, 95, 97, 99, 115, 120, 127, 129, 131, 133, 135, 170, 174, 185, 206-207 |
| src/news\_recap/orchestrator/controllers.py              |      284 |       23 |     92% |354, 387-390, 393-396, 404-407, 425, 446, 506-507, 515, 524, 546, 589, 605, 623 |
| src/news\_recap/orchestrator/failure\_classifier.py      |       42 |        3 |     93% |67, 100, 127 |
| src/news\_recap/orchestrator/intelligence.py             |      335 |       88 |     74% |168-178, 193-195, 237, 310-400, 407-418, 425-434, 437-487, 538-550, 555-568, 574-579, 637, 641-644, 646-658, 706, 735, 822 |
| src/news\_recap/orchestrator/metrics.py                  |      203 |       36 |     82% |37-39, 86-90, 116-119, 150, 266-268, 295, 320, 398, 414, 423, 443, 447-453, 477-481, 487, 495 |
| src/news\_recap/orchestrator/models.py                   |      291 |        0 |    100% |           |
| src/news\_recap/orchestrator/output\_fallback.py         |       89 |       51 |     43% |24, 28-30, 34, 37, 55, 59-61, 67, 75-77, 85-122, 127 |
| src/news\_recap/orchestrator/pricing.py                  |       47 |       23 |     51% |31-39, 46, 50, 54, 71-88 |
| src/news\_recap/orchestrator/repair.py                   |       14 |        2 |     86% |    30, 35 |
| src/news\_recap/orchestrator/repository.py               |      606 |      118 |     81% |203-204, 223-237, 257-258, 373, 487, 510, 544-545, 572, 576, 684, 699, 787-795, 884, 886, 888, 890, 909, 911, 933, 1003, 1025, 1066-1071, 1101-1130, 1139-1148, 1278-1286, 1314-1331, 1352, 1355, 1410-1425, 1455-1456, 1458, 1467-1529, 1562, 1638, 1647, 1674, 1690, 1724-1733, 1759-1767, 1802, 1866-1869, 1921, 1939-1940, 1961-1962, 1967-1968, 2000, 2003 |
| src/news\_recap/orchestrator/routing.py                  |      104 |       16 |     85% |65, 83, 85, 123, 128, 153, 188, 190, 193, 195, 198, 200, 202, 204, 206, 235 |
| src/news\_recap/orchestrator/sanitization.py             |       16 |        1 |     94% |        52 |
| src/news\_recap/orchestrator/services.py                 |       49 |        0 |    100% |           |
| src/news\_recap/orchestrator/smoke.py                    |      111 |       41 |     63% |72-89, 92-105, 146-149, 156, 176-192, 208, 211, 220-223, 228, 230, 240-255, 262 |
| src/news\_recap/orchestrator/usage.py                    |       71 |       10 |     86% |38, 62-65, 96-97, 116, 119-120 |
| src/news\_recap/orchestrator/validator.py                |       37 |        7 |     81% |40-41, 49, 57, 65, 74, 89 |
| src/news\_recap/orchestrator/workdir.py                  |       42 |        0 |    100% |           |
| src/news\_recap/orchestrator/worker.py                   |      410 |      125 |     70% |129-149, 157-176, 240-255, 269-295, 298-359, 381-401, 472-492, 516, 527, 530-549, 577-597, 621, 664, 677, 716, 817-823, 827, 843-868, 871-875, 884, 897, 900, 906, 921-928, 936-937, 939, 942, 946, 955, 958, 960, 963-964, 970, 980, 983, 985, 1001, 1027, 1034-1037, 1045, 1102, 1107 |
| **TOTAL**                                                | **5568** |  **896** | **84%** |           |


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