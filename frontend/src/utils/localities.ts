export interface LocalityOption {
  id: string;
  name: string;
  zone: string;
  wardCode?: string;
  latitude: number;
  longitude: number;
  isPilot?: boolean;
}

export const BENGALURU_LOCALITIES: LocalityOption[] = [
  {
    id: 'yelahanka',
    name: 'Yelahanka (Pilot Corridor)',
    zone: 'Yelahanka Zone',
    wardCode: 'BBMP-W004',
    latitude: 13.1007,
    longitude: 77.5963,
    isPilot: true,
  },
  {
    id: 'central',
    name: 'Central Bengaluru (Vidhana Soudha / MG Road)',
    zone: 'East Zone',
    wardCode: 'BBMP-W111',
    latitude: 12.9797,
    longitude: 77.5907,
    isPilot: false,
  },
  {
    id: 'indiranagar',
    name: 'Indiranagar',
    zone: 'East Zone',
    wardCode: 'BBMP-W080',
    latitude: 12.9784,
    longitude: 77.6408,
    isPilot: false,
  },
  {
    id: 'koramangala',
    name: 'Koramangala',
    zone: 'South Zone',
    wardCode: 'BBMP-W151',
    latitude: 12.9352,
    longitude: 77.6245,
    isPilot: false,
  },
  {
    id: 'whitefield',
    name: 'Whitefield',
    zone: 'Mahadevapura Zone',
    wardCode: 'BBMP-W084',
    latitude: 12.9698,
    longitude: 77.7500,
    isPilot: false,
  },
  {
    id: 'jayanagar',
    name: 'Jayanagar',
    zone: 'South Zone',
    wardCode: 'BBMP-W168',
    latitude: 12.9308,
    longitude: 77.5838,
    isPilot: false,
  },
  {
    id: 'malleshwaram',
    name: 'Malleshwaram',
    zone: 'West Zone',
    wardCode: 'BBMP-W045',
    latitude: 13.0031,
    longitude: 77.5643,
    isPilot: false,
  },
];

export const DEFAULT_PILOT_LOCALITY = BENGALURU_LOCALITIES[0];
