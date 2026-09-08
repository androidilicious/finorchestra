from __future__ import annotations

import numpy as np
import pandas as pd

from finorchestra.data.fred import FAR_FUTURE, wide_vintages_to_intervals
from finorchestra.utils import add_business_days, fridays_between


def test_wide_to_intervals_tracks_revisions_and_first_appearance():
    v = [pd.Timestamp("2020-04-03"), pd.Timestamp("2020-05-01"), pd.Timestamp("2020-06-05"), pd.Timestamp("2020-07-03")]
    wide = pd.DataFrame(
        {v[0]: [3.5, np.nan, np.nan], v[1]: [3.5, 4.4, np.nan], v[2]: [3.5, 4.4, 14.7], v[3]: [3.5, 4.5, 14.7]},
        index=pd.to_datetime(["2020-02-01", "2020-03-01", "2020-04-01"]),
    )
    iv = wide_vintages_to_intervals(wide)
    mar = iv[iv.observation_date == "2020-03-01"].reset_index(drop=True)
    assert len(mar) == 2
    assert mar.loc[0, "value"] == 4.4 and mar.loc[0, "realtime_start"] == v[1] and mar.loc[0, "realtime_end"] == v[3]
    assert mar.loc[1, "value"] == 4.5 and mar.loc[1, "realtime_start"] == v[3] and mar.loc[1, "realtime_end"] == FAR_FUTURE
    apr = iv[iv.observation_date == "2020-04-01"].iloc[0]
    assert apr["realtime_start"] == v[2]  # first visible in the June vintage


def test_as_of_filter_semantics():
    from finorchestra.data.fred import FredStore

    t = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(["2020-03-01", "2020-03-01", "2020-04-01"]),
            "value": [4.4, 4.5, 14.7],
            "realtime_start": pd.to_datetime(["2020-05-01", "2020-07-03", "2020-06-05"]),
            "realtime_end": [pd.Timestamp("2020-07-03"), FAR_FUTURE, FAR_FUTURE],
        }
    )
    fs = FredStore.__new__(FredStore)
    fs.tables = {"X": t}
    s_may = fs.as_of("X", pd.Timestamp("2020-05-15").date())
    assert s_may.to_dict() == {pd.Timestamp("2020-03-01"): 4.4}
    s_jul = fs.as_of("X", pd.Timestamp("2020-07-10").date())
    assert s_jul.loc["2020-03-01"] == 4.5 and s_jul.loc["2020-04-01"] == 14.7


def test_fridays_and_business_days():
    f = fridays_between(pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-01-31").date())
    assert [d.isoformat() for d in f] == ["2024-01-05", "2024-01-12", "2024-01-19", "2024-01-26"]
    assert add_business_days(pd.Timestamp("2024-01-05").date(), 2).isoformat() == "2024-01-09"  # Fri + 2 bd = Tue
