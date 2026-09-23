# e2e seeding data

Used only by `tools/experiment.py`, never by the rite: the reference solution of the cycle's tasks,
so a measurement can start from finished tasks and open fixes without spending tokens to get there.
The `.solution` suffix keeps `node --test` from picking the files up. The runs copy the example
without this folder and without `e2e.json`, so the model never sees the answer.
