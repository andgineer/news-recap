# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/agent\_runtime.py                        |       80 |       22 |     72% |38, 41-42, 47, 134, 136, 159-188 |
| src/news\_recap/brain/backend/base.py                    |       24 |        0 |    100% |           |
| src/news\_recap/brain/backend/benchmark\_agent.py        |       88 |       88 |      0% |     3-149 |
| src/news\_recap/brain/backend/cli\_backend.py            |      169 |       62 |     63% |24-25, 82-88, 116, 119, 151-202, 214, 227, 238-239, 246, 266-267, 286, 288, 292, 295, 306-307, 309, 355-356, 364-368, 379-390 |
| src/news\_recap/brain/backend/echo\_agent.py             |       40 |       40 |      0% |     19-90 |
| src/news\_recap/brain/contracts.py                       |      116 |       35 |     70% |80, 98, 100, 102, 115-148, 154, 173, 177, 191, 207-208 |
| src/news\_recap/brain/flows.py                           |      390 |       99 |     75% |183-193, 208-210, 251, 293-354, 362-373, 380-389, 392-435, 478-490, 495-508, 514-519, 635-638, 691-694, 785, 807, 811, 836-837, 865, 869-872, 874-886, 934, 968, 1075 |
| src/news\_recap/brain/models.py                          |      132 |        2 |     98% |    23, 35 |
| src/news\_recap/brain/pricing.py                         |       51 |        5 |     90% |41, 76, 79, 84-85 |
| src/news\_recap/brain/routing.py                         |      109 |       27 |     75% |53, 62, 80-110, 145, 150, 175, 210, 212, 215, 217, 220, 222, 224, 226, 228, 257 |
| src/news\_recap/brain/sanitization.py                    |       16 |        2 |     88% |    44, 52 |
| src/news\_recap/brain/usage.py                           |       91 |       29 |     68% |38, 42, 63-66, 89-91, 95-96, 100-101, 105-107, 109, 114-121, 135-141 |
| src/news\_recap/brain/workdir.py                         |       55 |        0 |    100% |           |
| src/news\_recap/config.py                                |      296 |       42 |     86% |265, 267, 269, 275, 283, 285, 305, 318, 320, 322, 324, 328, 330, 332, 334, 336, 338, 340, 370, 377, 393, 395, 405-406, 410, 426, 441, 443, 451, 461, 473, 475, 494-499, 505, 515, 522, 529 |
| src/news\_recap/http/fetcher.py                          |       42 |       20 |     52% |42-48, 58-81, 91, 94, 97 |
| src/news\_recap/http/html\_extractor.py                  |       29 |        9 |     69% |47-49, 52-62, 69 |
| src/news\_recap/http/youtube\_extractor.py               |       49 |       29 |     41% |    57-107 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        4 |     92% |41, 45-46, 75 |
| src/news\_recap/ingestion/controllers.py                 |      154 |       12 |     92% |143, 172, 194, 218, 241, 261, 293, 302, 338-339, 377, 388 |
| src/news\_recap/ingestion/dedup/calibration.py           |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/ingestion/dedup/cluster.py               |       74 |        4 |     95% |20, 58, 62, 128 |
| src/news\_recap/ingestion/dedup/embedder.py              |       71 |       14 |     80% |27-30, 40, 58, 61, 83-86, 89-91, 118 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      161 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       39 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      748 |      133 |     82% |140, 169, 209, 234, 264, 280-285, 303, 332-342, 466, 489-491, 555-559, 627, 665, 771-773, 821, 852, 880, 903-906, 978-985, 1039-1059, 1227, 1249, 1308-1313, 1468-1476, 1483-1512, 1521-1530, 1560-1577, 1598, 1601, 1658-1673, 1703-1704, 1706, 1717-1779, 1798, 1807, 1834, 1882-1891, 2032-2034, 2062, 2145, 2179, 2197-2198, 2219-2220, 2225-2226, 2258, 2261 |
| src/news\_recap/ingestion/services/dedup\_service.py     |       53 |        3 |     94% |    99-101 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      424 |      116 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 660-662, 673-678, 682-685, 725, 730, 734, 753-754, 764, 772 |
| src/news\_recap/ingestion/storage/alembic\_runner.py     |       12 |        0 |    100% |           |
| src/news\_recap/ingestion/storage/common.py              |       36 |        8 |     78% |24-27, 33-36 |
| src/news\_recap/ingestion/storage/sqlmodel\_models.py    |      250 |        0 |    100% |           |
| src/news\_recap/main.py                                  |      196 |        9 |     95% |367, 537, 586, 612, 677, 800, 842, 872, 964 |
| src/news\_recap/recap/agent\_task.py                     |       32 |       15 |     53% |     43-78 |
| src/news\_recap/recap/flow.py                            |      129 |      109 |     16% |60-149, 162-207, 219-248, 256-257, 267-329 |
| src/news\_recap/recap/launcher.py                        |       54 |       29 |     46% |45-53, 65-99, 108-118 |
| src/news\_recap/recap/pipeline\_io.py                    |       49 |       30 |     39% |40-42, 52-55, 69-101, 106-130 |
| src/news\_recap/recap/prompts.py                         |       10 |        0 |    100% |           |
| src/news\_recap/recap/resource\_loader.py                |       43 |       21 |     51% |39-41, 46-48, 51-59, 68-90, 99-100, 103, 106 |
| src/news\_recap/recap/runner.py                          |      201 |       18 |     91% |46-53, 56, 65, 109, 130-134, 287, 290, 404, 442 |
| src/news\_recap/recap/schemas.py                         |        8 |        0 |    100% |           |
| **TOTAL**                                                | **4774** | **1075** | **77%** |           |


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