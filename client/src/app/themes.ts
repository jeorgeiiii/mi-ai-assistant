export interface Theme {
  id: string;
  name: string;
  accent: string;
  images: string[];
}

export const THEMES: Theme[] = [
  {
    id: 'aurora',
    name: 'Aurora',
    accent: '#10b981',
    images: [
      'https://images.unsplash.com/photo-1506744038136-46273834b3fb',
      'https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05',
      'https://images.unsplash.com/photo-1441974231531-c6227db76b6e',
      'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee',
      'https://images.unsplash.com/photo-1519681393784-d120267933ba',
      'https://images.unsplash.com/photo-1472214103451-9374bd1c798e',
    ],
  },
  {
    id: 'ocean',
    name: 'Ocean',
    accent: '#06b6d4',
    images: [
      'https://images.unsplash.com/photo-1507525428034-b723cf961d3e',
      'https://images.unsplash.com/photo-1544551763-46a013bb70d5',
      'https://images.unsplash.com/photo-1520250497591-112f2f40a3f4',
      'https://images.unsplash.com/photo-1439405326854-014607f694d7',
      'https://images.unsplash.com/photo-1505142468610-359e7d316be0',
    ],
  },
  {
    id: 'cosmos',
    name: 'Cosmos',
    accent: '#8b5cf6',
    images: [
      'https://images.unsplash.com/photo-1462331940025-496dfbfc7564',
      'https://images.unsplash.com/photo-1446776653964-20c1d3a81b06',
      'https://images.unsplash.com/photo-1502134249126-9f3755a50d78',
      'https://images.unsplash.com/photo-1419242902214-272b3f66ee7a',
      'https://images.unsplash.com/photo-1451187580459-43490279c0fa',
    ],
  },
  {
    id: 'metropolis',
    name: 'Metropolis',
    accent: '#f59e0b',
    images: [
      'https://images.unsplash.com/photo-1449824913935-59a10b8d2000',
      'https://images.unsplash.com/photo-1477959858617-67f85cf4f1df',
      'https://images.unsplash.com/photo-1480714378408-67cf0d13bc1b',
      'https://images.unsplash.com/photo-1519501025264-65ba15a82390',
      'https://images.unsplash.com/photo-1496564203457-11bb12075d90',
    ],
  },
  {
    id: 'sunset',
    name: 'Sunset',
    accent: '#f43f5e',
    images: [
      'https://images.unsplash.com/photo-1495616811223-4d98c6e9c869',
      'https://images.unsplash.com/photo-1495805442109-bf1cf975750b',
      'https://images.unsplash.com/photo-1470252649378-9c29740c9fa8',
      'https://images.unsplash.com/photo-1444703686981-a3abbc4d4fe3',
    ],
  },
  {
    id: 'wildlife',
    name: 'Wildlife',
    accent: '#c2410c',
    images: [
      'https://images.unsplash.com/photo-1552410260-0fd9b577afa6',
      'https://images.unsplash.com/photo-1549366021-9f761d450615',
      'https://images.unsplash.com/photo-1456926631375-92c8ce872def',
      'https://images.unsplash.com/photo-1518291344630-4857135fb581',
      'https://images.unsplash.com/photo-1470093851219-69951fcbb533',
    ],
  },
  {
    id: 'rajasthan',
    name: 'Rajasthan',
    accent: '#db2777',
    images: [
      'https://images.unsplash.com/photo-1524492412937-b28074a5d7da',
      'https://images.unsplash.com/photo-1477587458883-47145ed94245',
      'https://images.unsplash.com/photo-1587922546307-776227941871',
      'https://images.unsplash.com/photo-1587474260584-136574528ed5',
      'https://images.unsplash.com/photo-1512343879784-a960bf40e7f2',
    ],
  },
  {
    id: 'desert',
    name: 'Desert',
    accent: '#ca8a04',
    images: [
      'https://images.unsplash.com/photo-1509316785289-025f5b846b35',
      'https://images.unsplash.com/photo-1473580044384-7ba9967e16a0',
      'https://images.unsplash.com/photo-1516450360452-9312f5e86fc7',
      'https://images.unsplash.com/photo-1414609245224-afa02bfb3fda',
      'https://images.unsplash.com/photo-1470770903676-69b98201ea1c',
    ],
  },
];

export const DEFAULT_THEME_ID = THEMES[0].id;

export function withParams(url: string, width: number, quality = 80): string {
  return `${url}?auto=format&fit=crop&w=${width}&q=${quality}`;
}

export function getTheme(id: string): Theme {
  return THEMES.find((t) => t.id === id) || THEMES[0];
}
