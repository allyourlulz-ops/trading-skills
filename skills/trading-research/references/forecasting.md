# Probabilistic forecasting with Kronos (MIT)
Install from the repo (`pip install -r requirements.txt`; import from `model/`). Weights on Hugging Face `NeoQuasar/*`.
```python
from model import Kronos, KronosTokenizer, KronosPredictor
tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
mdl = Kronos.from_pretrained("NeoQuasar/Kronos-small")
p = KronosPredictor(mdl, tok, max_context=512, clip=5)
pred = p.predict(df=x_df[['open','high','low','close','volume','amount']],
                 x_timestamp=x_ts, y_timestamp=y_ts, pred_len=20,
                 T=1.0, top_p=0.9, sample_count=20)
```
| Model | Context | Params |
|---|---|---|
| Kronos-mini | 2048 | 4.1M (Tokenizer-2k) |
| Kronos-small | 512 | 24.7M |
| Kronos-base | 512 | 102.3M |
Rules: run several samples/seeds and report the spread (e.g. 10th–90th percentile path), never a point target. One input among many, never the decision. Forecasts ignore fundamentals and costs; neutralise beta before calling anything alpha. GPU recommended. No NaNs allowed in input.
