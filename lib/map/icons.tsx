type ColoredPinProps = {
  color: string;
};

export function ColoredPin({ color }: ColoredPinProps) {
  return (
    <div className="purchase-map-pin">
      <span
        style={{
          display: "block",
          width: 22,
          height: 22,
          backgroundColor: color,
          border: "2px solid #fff",
          borderRadius: "50% 50% 50% 0",
          transform: "rotate(-45deg)",
          boxShadow: "0 2px 6px rgba(0,0,0,0.35)",
        }}
      />
    </div>
  );
}
