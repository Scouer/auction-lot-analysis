#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, re, time
sys.path.insert(0, "/Users/maxrusskikh/.claude-assistant/antiq")
from antiq_lib import *

IDS = ["1a03b5f0ddeb9bff","1a036399c80a18ca","1a0363947befd1fa","1a03637e1c8ea1e1",
       "1a03637ddc8e650e","1a069b7bc395223f","1a05a445b4fdd65f","1a03b5e5350e50d8",
       "1a036381a9ac4ad5","1a082647e6deaa07","1a06b9461da6bf37","1a0423e7dd6052cb",
       "1a06b94dc02510c6","1a0423e2fb7c1b65"]
for tid in IDS:
    for a in range(6):
        try:
            m = gmsg(tid); break
        except Exception as e:
            if "Quota" in str(e) or "rateLimit" in str(e): time.sleep(10); continue
            m = None; print(tid, "ERR", str(e)[:100]); break
    if not m: continue
    b = re.sub(r"\s+", " ", m["body"])
    print("=" * 60)
    print(m["subject"][:110])
    print(b[:900])
    print()
    time.sleep(1.0)
