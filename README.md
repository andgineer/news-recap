# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/automation.py                            |      253 |       15 |     94% |71, 102-103, 159-162, 183-185, 196-199, 547 |
| src/news\_recap/config.py                                |      289 |       56 |     81% |240-242, 255, 259, 261, 267, 282, 285, 290, 311, 313, 315, 317, 321, 323, 366, 373, 389, 391, 401-402, 406, 487, 489, 497, 512-529, 538, 540, 556-564, 570, 580, 587, 594 |
| src/news\_recap/http/fetcher.py                          |       42 |        4 |     90% |47, 92, 95, 98 |
| src/news\_recap/http/html\_extractor.py                  |       29 |        7 |     76% |47-49, 60-62, 69 |
| src/news\_recap/http/youtube\_extractor.py               |       94 |       15 |     84% |116-120, 140, 144, 158, 160-165, 190, 198 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        1 |     98% |        75 |
| src/news\_recap/ingestion/controllers.py                 |       40 |        1 |     98% |        91 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      149 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       35 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      258 |       33 |     87% |92, 134, 205, 215-235, 247, 316, 394, 544-550 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      424 |      116 |     73% |45, 56, 70, 81, 91, 100, 199, 324, 338, 351, 375-380, 401, 403, 414-454, 464-471, 480-503, 514-515, 521-522, 530-543, 594-632, 636-650, 660-662, 673-678, 682-685, 725, 730, 734, 753-754, 764, 772 |
| src/news\_recap/main.py                                  |      208 |       18 |     91% |206, 293, 318, 328, 356, 452-453, 460, 467-468, 529-532, 549-554, 582, 606, 608 |
| src/news\_recap/recap/agents/ai\_agent.py                |      161 |       80 |     50% |60-142, 146-149, 177-180, 185-191, 196-211, 302, 317, 336-342, 350-361 |
| src/news\_recap/recap/agents/api\_agent.py               |       58 |        1 |     98% |        79 |
| src/news\_recap/recap/agents/concurrency.py              |       41 |        0 |    100% |           |
| src/news\_recap/recap/agents/echo.py                     |       20 |       20 |      0% |     19-53 |
| src/news\_recap/recap/agents/routing.py                  |      131 |       14 |     89% |52, 73, 111, 117, 161, 166, 193, 228, 231, 233, 235, 237, 241, 248 |
| src/news\_recap/recap/agents/subprocess.py               |      162 |       83 |     49% |27-28, 62, 73, 85-86, 93, 110-111, 130, 132, 136, 139, 150-151, 153, 190-274, 278-281, 286-302, 306-317 |
| src/news\_recap/recap/agents/transport.py                |       10 |        0 |    100% |           |
| src/news\_recap/recap/agents/transport\_anthropic.py     |       19 |        1 |     95% |        35 |
| src/news\_recap/recap/article\_ordering.py               |       44 |        0 |    100% |           |
| src/news\_recap/recap/contracts.py                       |       67 |       21 |     69% |49-50, 58, 65, 76, 78, 80, 87, 93-125, 131 |
| src/news\_recap/recap/dedup/calibration.py               |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/recap/dedup/cluster.py                   |       51 |        2 |     96% |    62, 66 |
| src/news\_recap/recap/dedup/embedder.py                  |       71 |       15 |     79% |27-30, 40, 58, 61, 83-86, 89-91, 110, 117 |
| src/news\_recap/recap/digest\_info.py                    |      108 |        7 |     94% |28, 82-84, 100, 115, 127 |
| src/news\_recap/recap/export\_prompt.py                  |       78 |        5 |     94% |175-176, 185, 189-190 |
| src/news\_recap/recap/flow.py                            |       94 |       70 |     26% |42-56, 64-67, 80-181 |
| src/news\_recap/recap/launcher.py                        |       96 |       10 |     90% |86, 120, 153-168 |
| src/news\_recap/recap/loaders/resource\_cache.py         |       51 |        0 |    100% |           |
| src/news\_recap/recap/loaders/resource\_loader.py        |      138 |       18 |     87% |90, 121-127, 190-207, 211-213, 235, 257, 303, 312-313, 316, 319 |
| src/news\_recap/recap/models.py                          |       59 |        8 |     86% |42-47, 50, 59 |
| src/news\_recap/recap/pipeline\_setup.py                 |      209 |       16 |     92% |53-55, 122-123, 129, 140-146, 191-192, 219-220, 248-249, 342-343 |
| src/news\_recap/recap/storage/pipeline\_io.py            |      154 |       15 |     90% |71, 105-111, 134, 140-141, 155, 207, 218, 254 |
| src/news\_recap/recap/storage/schemas.py                 |        1 |        1 |      0% |         7 |
| src/news\_recap/recap/storage/workdir.py                 |       53 |       32 |     40% |35, 45-76, 84-87, 100-103, 117-137 |
| src/news\_recap/recap/tasks/base.py                      |       69 |       22 |     68% |63-80, 110, 133-151, 154 |
| src/news\_recap/recap/tasks/classify.py                  |      151 |       20 |     87% |139, 145, 220-230, 238, 245-246, 251, 295-297 |
| src/news\_recap/recap/tasks/deduplicate.py               |      235 |      110 |     53% |59-63, 67-71, 108-113, 228-255, 263-283, 292-308, 321-388, 399-414, 427-428, 438-450, 460-464 |
| src/news\_recap/recap/tasks/enrich.py                    |      187 |       15 |     92% |144, 210, 237-238, 301-306, 326-330, 340, 353-354, 396 |
| src/news\_recap/recap/tasks/load\_resources.py           |       55 |        6 |     89% |42, 81-82, 88-90 |
| src/news\_recap/recap/tasks/oneshot\_digest.py           |      359 |      130 |     64% |161, 168-171, 197, 251-287, 305-324, 333-351, 359-385, 393-425, 516, 641-717, 726 |
| src/news\_recap/recap/tasks/parallel.py                  |       80 |       19 |     76% |37-38, 95-96, 102, 121-128, 150, 157-160, 180 |
| src/news\_recap/recap/tasks/prompts.py                   |       21 |        0 |    100% |           |
| src/news\_recap/recap/tasks/refine\_layout.py            |      115 |       24 |     79% |216-255, 262 |
| src/news\_recap/storage/io.py                            |       50 |        5 |     90% | 35-38, 61 |
| src/news\_recap/web/server.py                            |      129 |       31 |     76% |32-34, 60-62, 71-72, 90, 94-96, 142-143, 162, 182-206 |
| **TOTAL**                                                | **5401** | **1106** | **80%** |           |


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