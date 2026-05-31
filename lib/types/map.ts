export type MapEmployee = {
  id: string;
  name: string;
  transaction_count: number;
};

export type MapPurchasePoint = {
  transaction_id: string;
  lat: number;
  lng: number;
  city: string;
  merchant_name: string;
  merchant_category: string;
  amount: number;
  date: string;
  flag_count: number;
};

export type MapSegmentEndpoint = {
  lat: number;
  lng: number;
  city: string;
  date: string;
  transaction_id: string;
};

export type MapSegment = {
  from: MapSegmentEndpoint;
  to: MapSegmentEndpoint;
  days_between: number;
};

export type MapEmployeePurchases = {
  employee_id: string;
  name: string;
  points: MapPurchasePoint[];
  segments: MapSegment[];
};

export type MapPurchasesResponse = {
  employees: MapEmployeePurchases[];
};
