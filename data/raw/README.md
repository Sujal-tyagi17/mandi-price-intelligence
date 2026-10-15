# Raw data

Put the downloaded mandi price files here, one sub-folder per source:

```
data/raw/
├── ceda/        CEDA Agri-Market CSV downloads (recommended)
├── agmarknet/   Agmarknet "Price and Arrivals" exports (.xls / .xlsx)
└── datagov/     data.gov.in API files written by src/fetch_datagov.py
```

See [DATA.md](../../DATA.md) for step-by-step download instructions. Any `.csv`, `.csv.gz`,
`.xls`, `.xlsx` or `.json` file in these folders is read by `python run_all.py`.
