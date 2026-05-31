const cadFormatter = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
});

export function formatCad(amount: number): string {
  return cadFormatter.format(amount);
}
