// Placeholder / example data for the frontend (no backend yet).
// Real values arrive when we wire up /api/v1/query in the next phase.

export const STATS = {
  transactions: "100,000",
  revenue: "$175M",
  docs: "43",
  chunks: "425",
  regions: "5",
  months: "12",
  retailers: "9",
  categories: "5",
  liveSources: "9",
};

export const SQL_SAMPLE = [
  { date: "2024-10-04", region: "West", product: "Electronics", payment: "Card", revenue: "$1,284" },
  { date: "2024-10-04", region: "South", product: "Home", payment: "PayPal", revenue: "$342" },
  { date: "2024-10-05", region: "North", product: "Sports", payment: "Card", revenue: "$918" },
  { date: "2024-10-05", region: "East", product: "Food", payment: "Cash", revenue: "$76" },
];

export const DOC_CATEGORIES = [
  { name: "Financial reports", count: 7 },
  { name: "Contracts", count: 6 },
  { name: "Strategy decks", count: 5 },
  { name: "SOPs / policy", count: 9 },
  { name: "Incident reports", count: 4 },
  { name: "Analyst memos", count: 12 },
];

export const WEB_SAMPLE = [
  { retailer: "Newegg", category: "Electronics", product: "Power station", price: "$999" },
  { retailer: "IKEA", category: "Home", product: "Shelf unit", price: "$149" },
  { retailer: "Campmor", category: "Sports", product: "Tent 2P", price: "$219" },
  { retailer: "Swanson", category: "Food", product: "Vitamin D3", price: "$11" },
];

// small chart datasets for the right-hand visual on the data section
export const REGION_REVENUE = [
  { label: "West", value: 52 },
  { label: "North", value: 41 },
  { label: "East", value: 33 },
  { label: "South", value: 28 },
  { label: "Central", value: 21 },
];
export const WEB_AVG_PRICE = [
  { label: "Electronics", value: 640 },
  { label: "Sports", value: 190 },
  { label: "Home", value: 180 },
  { label: "Food", value: 24 },
];

export const CHAPTERS = [
  { n: "01", title: "The data", sub: "See what Nexus knows", href: "/how" },
  { n: "02", title: "The agents", sub: "How answers get built", href: "/how#agents" },
  { n: "03", title: "Context", sub: "Glossary, schema, ontology", href: "/context" },
  { n: "04", title: "Reliability", sub: "The learning loop, evidenced", href: "/reliability" },
  { n: "05", title: "Ask Nexus", sub: "Try it live", href: "/ask" },
];
