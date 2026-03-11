# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      282 |       56 |     80% |245-247, 260, 264, 266, 272, 287, 290, 295, 316, 318, 320, 322, 326, 328, 371, 378, 394, 396, 406-407, 411, 503, 505, 513, 528-545, 554, 556, 572-580, 586, 596, 603, 610 |
| src/news\_recap/http/fetcher.py                          |       42 |        4 |     90% |47, 92, 95, 98 |
| src/news\_recap/http/html\_extractor.py                  |       29 |        7 |     76% |47-49, 60-62, 69 |
| src/news\_recap/http/youtube\_extractor.py               |       94 |       15 |     84% |116-120, 140, 144, 158, 160-165, 190, 198 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        1 |     98% |        75 |
| src/news\_recap/ingestion/controllers.py                 |       66 |        3 |     95% |110, 129, 176 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      149 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       35 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      255 |       17 |     93% |92, 134, 205, 219, 221, 229-234, 247, 316, 394, 542-545 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      424 |      116 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 660-662, 673-678, 682-685, 725, 730, 734, 753-754, 764, 772 |
| src/news\_recap/main.py                                  |       70 |        3 |     96% |203, 261, 308 |
| src/news\_recap/recap/agents/ai\_agent.py                |      158 |      106 |     33% |60-135, 139-142, 170-173, 178-184, 189-204, 270-324, 332-343 |
| src/news\_recap/recap/agents/api\_agent.py               |       58 |        1 |     98% |        74 |
| src/news\_recap/recap/agents/concurrency.py              |       41 |        0 |    100% |           |
| src/news\_recap/recap/agents/echo.py                     |       20 |       20 |      0% |     19-53 |
| src/news\_recap/recap/agents/routing.py                  |      130 |       16 |     88% |51, 70-72, 109, 115, 159, 164, 191, 226, 229, 231, 233, 235, 239, 246 |
| src/news\_recap/recap/agents/subprocess.py               |      162 |       83 |     49% |27-28, 62, 73, 85-86, 93, 110-111, 130, 132, 136, 139, 150-151, 153, 190-274, 278-281, 286-302, 306-317 |
| src/news\_recap/recap/agents/transport.py                |       10 |        0 |    100% |           |
| src/news\_recap/recap/agents/transport\_anthropic.py     |       19 |        1 |     95% |        35 |
| src/news\_recap/recap/contracts.py                       |       67 |       21 |     69% |49-50, 58, 65, 76, 78, 80, 87, 93-125, 131 |
| src/news\_recap/recap/dedup/calibration.py               |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/recap/dedup/cluster.py                   |       51 |        2 |     96% |    62, 66 |
| src/news\_recap/recap/dedup/embedder.py                  |       71 |       15 |     79% |27-30, 40, 58, 61, 83-86, 89-91, 110, 117 |
| src/news\_recap/recap/export\_prompt.py                  |       96 |       18 |     81% |   161-187 |
| src/news\_recap/recap/flow.py                            |       98 |       71 |     28% |46-60, 64-67, 80-175 |
| src/news\_recap/recap/launcher.py                        |       90 |       22 |     76% |75, 87, 90-92, 95-101, 105, 122-134, 194-222 |
| src/news\_recap/recap/loaders/resource\_cache.py         |       51 |        0 |    100% |           |
| src/news\_recap/recap/loaders/resource\_loader.py        |      138 |       18 |     87% |90, 121-127, 190-207, 211-213, 235, 257, 303, 312-313, 316, 319 |
| src/news\_recap/recap/models.py                          |       53 |        8 |     85% |24-29, 32, 41 |
| src/news\_recap/recap/storage/pipeline\_io.py            |      152 |       17 |     89% |48, 52, 70, 103-109, 132, 138-139, 153, 205, 216, 251 |
| src/news\_recap/recap/storage/schemas.py                 |        1 |        1 |      0% |         7 |
| src/news\_recap/recap/storage/workdir.py                 |       53 |       32 |     40% |35, 45-76, 84-87, 100-103, 117-137 |
| src/news\_recap/recap/tasks/base.py                      |       67 |       11 |     84% |65-82, 136-138, 147, 151, 154 |
| src/news\_recap/recap/tasks/classify.py                  |      151 |       20 |     87% |139, 145, 220-230, 238, 245-246, 251, 291-293 |
| src/news\_recap/recap/tasks/deduplicate.py               |      235 |      110 |     53% |59-63, 67-71, 108-113, 228-255, 260-280, 289-305, 318-380, 391-406, 419-420, 430-442, 452-456 |
| src/news\_recap/recap/tasks/enrich.py                    |      187 |       15 |     92% |144, 210, 237-238, 301-306, 326-330, 340, 353-354, 395 |
| src/news\_recap/recap/tasks/group\_sections.py           |      110 |       20 |     82% |77, 149, 201-233 |
| src/news\_recap/recap/tasks/load\_resources.py           |       55 |        6 |     89% |42, 81-82, 88-90 |
| src/news\_recap/recap/tasks/map\_blocks.py               |      152 |       11 |     93% |123, 181, 194, 197, 241, 253-255, 271-272, 315 |
| src/news\_recap/recap/tasks/parallel.py                  |       80 |       19 |     76% |37-38, 95-96, 102, 121-128, 150, 157-160, 180 |
| src/news\_recap/recap/tasks/prompts.py                   |       23 |        0 |    100% |           |
| src/news\_recap/recap/tasks/reduce\_blocks.py            |      226 |       69 |     69% |65, 171, 213-216, 313-331, 347-359, 367-443, 452-465 |
| src/news\_recap/recap/tasks/split\_blocks.py             |       92 |        1 |     99% |       115 |
| src/news\_recap/recap/tasks/summarize.py                 |       40 |        9 |     78% |     75-90 |
| src/news\_recap/storage/io.py                            |       50 |        5 |     90% | 35-38, 61 |
| src/news\_recap/web/server.py                            |       96 |       14 |     85% |31-33, 59-61, 70-71, 120, 142-146 |
| **TOTAL**                                                | **4782** | **1023** | **79%** |           |


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