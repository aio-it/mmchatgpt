import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SportInfo:
    """Represents sport-specific information"""
    type: str
    eftp: Optional[float] = None

@dataclass
class IntervalsWellness:
    """
    Represents a wellness entry from Intervals.icu API
    """
    id: str  # Date in YYYY-MM-DD format
    ctl: Optional[float] = None
    atl: Optional[float] = None
    rampRate: Optional[float] = None
    ctlLoad: Optional[float] = None
    atlLoad: Optional[float] = None
    sportInfo: Optional[List[SportInfo]] = None
    updated: Optional[str] = None
    weight: Optional[float] = None
    restingHR: Optional[int] = None
    hrv: Optional[float] = None
    hrvSDNN: Optional[float] = None
    menstrualPhase: Optional[str] = None
    menstrualPhasePredicted: Optional[bool] = None
    kcalConsumed: Optional[int] = None
    sleepSecs: Optional[int] = None
    sleepScore: Optional[float] = None
    sleepQuality: Optional[int] = None
    avgSleepingHR: Optional[float] = None
    soreness: Optional[int] = None
    fatigue: Optional[int] = None
    stress: Optional[int] = None
    mood: Optional[int] = None
    motivation: Optional[int] = None
    injury: Optional[int] = None
    spO2: Optional[float] = None
    systolic: Optional[int] = None
    diastolic: Optional[int] = None
    hydration: Optional[int] = None
    hydrationVolume: Optional[float] = None
    readiness: Optional[int] = None
    baevskySI: Optional[float] = None
    bloodGlucose: Optional[float] = None
    lactate: Optional[float] = None
    bodyFat: Optional[float] = None
    abdomen: Optional[float] = None
    vo2max: Optional[float] = None
    comments: Optional[str] = None
    steps: Optional[int] = None
    respiration: Optional[float] = None
    locked: Optional[bool] = None

    @classmethod
    def from_dict(cls, data: dict) -> 'IntervalsWellness':
        """
        Create an IntervalsWellness instance from a dictionary
        
        Args:
            data: Dictionary containing wellness data from Intervals.icu API
            
        Returns:
            IntervalsWellness: A new instance of IntervalsWellness
        """
        # Handle sportInfo separately
        sport_info = data.pop('sportInfo', None)
        if sport_info:
            data['sportInfo'] = [SportInfo(**sport) for sport in sport_info]
            
        return cls(**{k: v for k, v in data.items() if not isinstance(v, dict)})
    
    def to_dict(self) -> dict:
        """
        Convert the IntervalsWellness instance to a dictionary
        
        Returns:
            dict: Dictionary representation of the wellness entry
        """
        data = {k: v for k, v in self.__dict__.items() if v is not None}
        if self.sportInfo:
            data['sportInfo'] = [vars(sport) for sport in self.sportInfo]
        return data
    def to_json(self) -> str:
        """export to json"""
        return json.dumps(self.to_dict())
