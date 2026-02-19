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
| src/news\_recap/ingestion/storage/sqlmodel\_models.py    |      309 |        0 |    100% |           |
| src/news\_recap/main.py                                  |      258 |       10 |     96% |581, 597, 768, 938, 987, 1013, 1078, 1201, 1243, 1273 |
| src/news\_recap/orchestrator/backend/base.py             |       21 |        0 |    100% |           |
| src/news\_recap/orchestrator/backend/benchmark\_agent.py |       80 |       38 |     52% |39-40, 43-50, 63-67, 70-71, 101-107, 111-112, 116-127 |
| src/news\_recap/orchestrator/backend/cli\_backend.py     |       56 |       12 |     79% |71, 82-83, 99, 103-115, 123-124, 131 |
| src/news\_recap/orchestrator/backend/echo\_agent.py      |       19 |        0 |    100% |           |
| src/news\_recap/orchestrator/contracts.py                |      112 |       16 |     86% |77, 95, 97, 99, 115, 120, 127, 129, 131, 133, 135, 170, 174, 185, 206-207 |
| src/news\_recap/orchestrator/controllers.py              |      223 |       17 |     92% |324, 357-360, 363-366, 373-374, 382, 391, 413, 456, 472, 490 |
| src/news\_recap/orchestrator/failure\_classifier.py      |       42 |        3 |     93% |67, 100, 127 |
| src/news\_recap/orchestrator/intelligence.py             |      335 |       88 |     74% |168-178, 193-195, 237, 310-400, 407-418, 425-434, 437-487, 538-550, 555-568, 574-579, 637, 641-644, 646-658, 706, 735, 822 |
| src/news\_recap/orchestrator/metrics.py                  |      203 |       36 |     82% |37-39, 86-90, 116-119, 150, 266-268, 295, 320, 398, 414, 423, 443, 447-453, 477-481, 487, 495 |
| src/news\_recap/orchestrator/models.py                   |      215 |        0 |    100% |           |
| src/news\_recap/orchestrator/repair.py                   |       14 |        2 |     86% |    30, 35 |
| src/news\_recap/orchestrator/repository.py               |      505 |      103 |     80% |198-199, 218-232, 252-253, 368, 482, 505, 539-540, 567, 571, 679, 694, 773, 795, 836-841, 871-900, 909-918, 1048-1056, 1084-1101, 1122, 1125, 1180-1195, 1225-1226, 1228, 1237-1299, 1332, 1408, 1417, 1444, 1460, 1494-1503, 1529-1537, 1572, 1648, 1666-1667, 1688-1689, 1694-1695, 1727, 1730 |
| src/news\_recap/orchestrator/routing.py                  |      104 |       16 |     85% |65, 83, 85, 123, 128, 153, 188, 190, 193, 195, 198, 200, 202, 204, 206, 235 |
| src/news\_recap/orchestrator/services.py                 |       49 |        0 |    100% |           |
| src/news\_recap/orchestrator/smoke.py                    |      111 |       41 |     63% |72-89, 92-105, 146-149, 156, 176-192, 208, 211, 220-223, 228, 230, 240-255, 262 |
| src/news\_recap/orchestrator/validator.py                |       37 |        8 |     78% |31, 40-41, 49, 57, 65, 74, 89 |
| src/news\_recap/orchestrator/workdir.py                  |       42 |        0 |    100% |           |
| src/news\_recap/orchestrator/worker.py                   |      302 |       94 |     69% |102-112, 120-129, 169-184, 198-214, 217-266, 288-298, 324-333, 360-370, 402, 415, 464-470, 485-510, 513-517, 526, 539, 542, 548, 554, 557, 559, 562-563, 569, 579, 582, 584, 600, 626, 633-636, 644, 701, 706 |
| **TOTAL**                                                | **4945** |  **760** | **85%** |           |


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