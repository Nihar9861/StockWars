import random
from decimal import Decimal
from sqlalchemy import func, select
from ..config import settings
from ..models import Company, MarketState, Sector

DATA = {
 "Technology": [("NovaByte Systems","NVBY"),("QuantumLeaf Software","QLFS"),("PixelForge Labs","PXFG")],
 "Artificial Intelligence": [("NeuroSphere AI","NRSP"),("Cognitra Dynamics","CGTD"),("SynapseWorks","SYNW")],
 "Banking": [("Meridian Trust Bank","MRTB"),("Crestline Capital","CRCP"),("Ironvault Financial","IRVF")],
 "Energy": [("SolarisGrid Power","SLGP"),("Petrovia Oil & Gas","PTVG"),("WindCrest Energy","WNDC")],
 "Healthcare": [("VitaCure Pharma","VTCR"),("HelixMed Labs","HLXM"),("CarePulse Hospitals","CPLS")],
 "Automobile": [("Veloxa Motors","VLXM"),("TorqueWorks Auto","TRQW"),("ElectraDrive","EDRV")],
 "FMCG": [("FreshNest Foods","FRNS"),("HomeBloom Products","HMBL"),("GoldenGrain Co","GGRN")],
 "Telecommunications": [("SignalWave Telecom","SGWV"),("Orbitel Networks","ORBT"),("LinkSphere Comms","LNKS")],
 "Real Estate": [("Skyline Habitat","SKHB"),("UrbanNest Realty","URBN"),("TerraHomes","TRHM")],
 "Infrastructure": [("BridgeMark Infra","BRMK"),("Titanbuild Construction","TTBL"),("RailNova Projects","RLNV")],
 "Entertainment": [("StarReel Studios","STRL"),("PlayVerse Games","PLVR"),("BeatBox Media","BTBX")],
 "Mining": [("DeepRock Minerals","DPRK"),("Ironcrest Mining","IRCM"),("AuraGold Resources","ARGD")],
}
SECTOR_VOL = {"Technology": .012, "Artificial Intelligence": .016, "Banking": .008, "Energy": .012, "Healthcare": .010,
              "Automobile": .011, "FMCG": .006, "Telecommunications": .008, "Real Estate": .010,
              "Infrastructure": .009, "Entertainment": .014, "Mining": .013}
CEOS = ["Arjun Mehta", "Riya Kapoor", "Vikram Sethi", "Anaya Rao", "Kabir Malhotra", "Isha Nair", "Rohan Bajaj", "Tara Iyer"]


async def seed(s):
    if (await s.execute(select(func.count()).select_from(Company))).scalar_one() == 0:
        for sname, comps in DATA.items():
            sec = Sector(name=sname)
            s.add(sec)
            await s.flush()
            for name, tick in comps:
                r = random.Random(f"{settings.seed}:{tick}")
                price = Decimal(r.randint(50, 1500)).quantize(Decimal("0.0001"))
                vol = SECTOR_VOL[sname] * r.uniform(0.8, 1.3)
                s.add(Company(name=name, ticker=tick, sector_id=sec.id, ceo=r.choice(CEOS),
                              description=f"{name} is a fictional {sname} company.",
                              total_shares=r.randint(1, 10) * 1_000_000, price=price, prev_close=price,
                              revenue=Decimal(r.randint(50, 900)) * 10_000_000,
                              profit=Decimal(r.randint(-5, 120)) * 1_000_000, debt=Decimal(r.randint(0, 300)) * 1_000_000,
                              reputation=r.randint(40, 85), growth_rate=r.uniform(-2, 12), volatility=vol,
                              risk_level="HIGH" if vol > .013 else "LOW" if vol < .008 else "MEDIUM"))
    if await s.get(MarketState, 1) is None:
        s.add(MarketState(id=1))
