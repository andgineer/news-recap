# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/automation.py                            |      246 |       15 |     94% |74, 105-106, 162-165, 186-188, 199-202, 552 |
| src/news\_recap/config.py                                |      274 |       10 |     96% |273, 275, 281, 301, 358, 448, 468, 478, 485, 492 |
| src/news\_recap/config\_file.py                          |      165 |        1 |     99% |       216 |
| src/news\_recap/http/fetcher.py                          |       42 |        4 |     90% |50, 95, 98, 101 |
| src/news\_recap/http/html\_extractor.py                  |       29 |        7 |     76% |47-49, 60-62, 69 |
| src/news\_recap/http/youtube\_extractor.py               |       94 |       15 |     84% |116-120, 140, 144, 158, 160-165, 190, 198 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        1 |     98% |        75 |
| src/news\_recap/ingestion/controllers.py                 |       40 |        1 |     98% |        91 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      149 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       34 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      264 |       27 |     90% |91, 206, 216-236, 248, 317, 395, 553-554 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      437 |       41 |     91% |47, 58, 72, 83, 93, 102, 201, 326, 340, 353, 377-382, 403, 405, 439, 449, 453, 457, 550-551, 557-558, 566-579, 761, 766, 770, 789-790, 800, 808 |
| src/news\_recap/main.py                                  |      362 |       13 |     96% |370, 422, 450, 576-577, 665-668, 685-690, 718, 866, 868 |
| src/news\_recap/operation\_config.py                     |       42 |        0 |    100% |           |
| src/news\_recap/recap/agents/ai\_agent.py                |      226 |       68 |     70% |65-166, 170-173, 286-292, 362, 369, 447, 449, 485-491, 499-507 |
| src/news\_recap/recap/agents/api\_agent.py               |       58 |        1 |     98% |        79 |
| src/news\_recap/recap/agents/concurrency.py              |       41 |        0 |    100% |           |
| src/news\_recap/recap/agents/routing.py                  |      131 |       14 |     89% |52, 73, 111, 117, 161, 166, 193, 228, 231, 233, 235, 237, 241, 248 |
| src/news\_recap/recap/agents/subprocess.py               |      164 |       43 |     74% |27-28, 62, 73, 85-86, 93, 110-111, 130, 132, 136, 139, 150-151, 153, 244-257, 260-272, 275-277, 281-284, 294, 299-300, 312-313, 316-321 |
| src/news\_recap/recap/agents/transport.py                |       10 |        0 |    100% |           |
| src/news\_recap/recap/agents/transport\_anthropic.py     |       19 |        1 |     95% |        35 |
| src/news\_recap/recap/article\_ordering.py               |       44 |        0 |    100% |           |
| src/news\_recap/recap/contracts.py                       |       71 |        6 |     92% |74, 92, 94, 96, 126-127 |
| src/news\_recap/recap/dedup/calibration.py               |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/recap/dedup/cluster.py                   |       51 |        2 |     96% |    62, 66 |
| src/news\_recap/recap/dedup/embedder.py                  |       71 |       15 |     79% |27-30, 40, 58, 61, 83-88, 91-93, 112, 119 |
| src/news\_recap/recap/digest\_info.py                    |      145 |       11 |     92% |28, 82-84, 102, 123, 194, 196-201 |
| src/news\_recap/recap/exceptions.py                      |        6 |        0 |    100% |           |
| src/news\_recap/recap/export\_prompt.py                  |      119 |        4 |     97% |153, 272, 276-277 |
| src/news\_recap/recap/flow.py                            |      115 |       66 |     43% |76-80, 91-96, 100-103, 116-223 |
| src/news\_recap/recap/jev/classify.py                    |       40 |        0 |    100% |           |
| src/news\_recap/recap/jev/client.py                      |       47 |        0 |    100% |           |
| src/news\_recap/recap/jev/dedup.py                       |      107 |        0 |    100% |           |
| src/news\_recap/recap/jev/policy.py                      |       16 |        0 |    100% |           |
| src/news\_recap/recap/jev/usage.py                       |       27 |        0 |    100% |           |
| src/news\_recap/recap/launcher.py                        |      243 |       15 |     94% |98, 125, 255, 258-259, 287-288, 290, 294, 297-299, 407, 458-459 |
| src/news\_recap/recap/loaders/resource\_cache.py         |       51 |        0 |    100% |           |
| src/news\_recap/recap/loaders/resource\_loader.py        |      138 |       18 |     87% |90, 121-127, 190-207, 211-213, 235, 257, 303, 312-313, 316, 319 |
| src/news\_recap/recap/models.py                          |       61 |        8 |     87% |45-50, 53, 62 |
| src/news\_recap/recap/pipeline\_setup.py                 |      255 |        9 |     96% |58-60, 175-176, 212-213, 377-378 |
| src/news\_recap/recap/storage/pipeline\_io.py            |      161 |       15 |     91% |78, 118-124, 147, 153-154, 168, 220, 231, 267 |
| src/news\_recap/recap/storage/workdir.py                 |       48 |        1 |     98% |        93 |
| src/news\_recap/recap/tasks/base.py                      |       77 |       22 |     71% |68-69, 83-97, 120, 143-161, 164 |
| src/news\_recap/recap/tasks/classify.py                  |      180 |       16 |     91% |144, 150, 226-236, 251-252, 260 |
| src/news\_recap/recap/tasks/deduplicate.py               |      293 |       47 |     84% |73, 139-144, 263-264, 271, 277, 428-429, 447-463, 476-547, 561, 621 |
| src/news\_recap/recap/tasks/enrich.py                    |      188 |       15 |     92% |145, 212, 239-240, 303-308, 328-332, 342, 355-356, 398 |
| src/news\_recap/recap/tasks/load\_resources.py           |       55 |        6 |     89% |39, 78-79, 85-87 |
| src/news\_recap/recap/tasks/oneshot\_digest.py           |      413 |      177 |     57% |165, 172-175, 201, 255-291, 312-327, 332-335, 355-391, 400-419, 427-453, 461-493, 584, 711-735, 753-845, 854 |
| src/news\_recap/recap/tasks/parallel.py                  |       80 |       19 |     76% |37-38, 95-96, 102, 121-128, 150, 157-160, 180 |
| src/news\_recap/recap/tasks/prompts.py                   |       22 |        0 |    100% |           |
| src/news\_recap/recap/tasks/refine\_layout.py            |      115 |       24 |     79% |223-263, 270 |
| src/news\_recap/storage/io.py                            |       48 |        5 |     90% | 32-35, 59 |
| src/news\_recap/web/server.py                            |      131 |       30 |     77% |37-39, 65-67, 76-77, 95, 99-101, 147-148, 169, 189-208 |
| **TOTAL**                                                | **6498** |  **832** | **87%** |           |


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