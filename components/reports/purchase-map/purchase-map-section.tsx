"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CircleNotchIcon } from "@phosphor-icons/react";
import { EmployeeMapFilter } from "@/components/reports/purchase-map/employee-map-filter";
import { MapLegend } from "@/components/reports/purchase-map/map-legend";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getEmployees } from "@/lib/api/employees";
import { getMapPurchases } from "@/lib/api/map";
import { buildEmployeeColorIndex } from "@/lib/map/colors";
import type { EmployeeRosterEntry } from "@/lib/types/brim";
import type { MapPurchasesResponse } from "@/lib/types/map";

const PurchaseMap = dynamic(() => import("./purchase-map-inner"), {
  ssr: false,
  loading: () => (
    <div className="h-[min(50vh,480px)] min-h-[360px] w-full animate-pulse rounded-lg bg-muted/30" />
  ),
});

function idsWithGeoPurchases(
  roster: EmployeeRosterEntry[],
  ids: string[]
): string[] {
  return ids.filter((id) => {
    const emp = roster.find((e) => e.id === id);
    return emp != null && emp.map_transaction_count > 0;
  });
}

export function PurchaseMapSection() {
  const [employees, setEmployees] = useState<EmployeeRosterEntry[]>([]);
  const [employeesLoading, setEmployeesLoading] = useState(true);
  const [employeesError, setEmployeesError] = useState<string | null>(null);

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [purchases, setPurchases] = useState<MapPurchasesResponse | null>(null);
  const [purchasesLoading, setPurchasesLoading] = useState(false);
  const [purchasesError, setPurchasesError] = useState<string | null>(null);

  const colorIndex = useMemo(
    () => buildEmployeeColorIndex(employees),
    [employees]
  );

  const purchasesEmployeeIds = useMemo(
    () => idsWithGeoPurchases(employees, selectedIds),
    [employees, selectedIds]
  );

  const loadEmployees = useCallback(async () => {
    setEmployeesLoading(true);
    setEmployeesError(null);
    try {
      const data = await getEmployees();
      setEmployees(data);
    } catch (err) {
      setEmployeesError(
        err instanceof Error ? err.message : "Failed to load employees"
      );
    } finally {
      setEmployeesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadEmployees();
  }, [loadEmployees]);

  useEffect(() => {
    if (purchasesEmployeeIds.length === 0) {
      setPurchases(null);
      setPurchasesError(null);
      setPurchasesLoading(false);
      return;
    }

    let cancelled = false;
    setPurchasesLoading(true);
    setPurchasesError(null);

    void getMapPurchases({
      employee_ids: purchasesEmployeeIds,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    })
      .then((data) => {
        if (!cancelled) setPurchases(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setPurchases(null);
          setPurchasesError(
            err instanceof Error ? err.message : "Failed to load purchases"
          );
        }
      })
      .finally(() => {
        if (!cancelled) setPurchasesLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [purchasesEmployeeIds, dateFrom, dateTo]);

  const mapEmployees = purchases?.employees ?? [];
  const totalPoints = mapEmployees.reduce((n, e) => n + e.points.length, 0);

  const boundsKey = useMemo(() => {
    const parts: string[] = [purchasesEmployeeIds.join(","), dateFrom, dateTo];
    for (const emp of mapEmployees) {
      for (const p of emp.points) {
        parts.push(`${p.transaction_id}:${p.lat},${p.lng}`);
      }
    }
    return parts.join("|");
  }, [purchasesEmployeeIds, dateFrom, dateTo, mapEmployees]);

  const showMap =
    purchasesEmployeeIds.length > 0 &&
    !purchasesLoading &&
    !purchasesError &&
    totalPoints > 0;

  const mapEmptyMessage =
    purchasesEmployeeIds.length === 0
      ? selectedIds.length === 0
        ? "Select one or more employees to show purchases on the map."
        : "Selected employees have no geolocated purchases."
      : purchasesLoading
        ? null
        : totalPoints === 0
          ? "No purchases in this period for the selected employees."
          : null;

  if (employeesLoading) {
    return (
      <Card className="border-border/50 shadow-none">
        <CardHeader>
          <CardTitle className="text-base font-medium">Purchase map</CardTitle>
          <CardDescription>Employee travel and purchase locations</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="py-12 text-center text-sm text-muted-foreground">
            Loading employees…
          </p>
        </CardContent>
      </Card>
    );
  }

  if (employeesError) {
    return (
      <Card className="border-border/50 shadow-none">
        <CardHeader>
          <CardTitle className="text-base font-medium">Purchase map</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-4 py-8">
          <p className="text-sm text-destructive">{employeesError}</p>
          <Button variant="outline" onClick={() => void loadEmployees()}>
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-border/50 shadow-none">
      <CardHeader>
        <CardTitle className="text-base font-medium">Purchase map</CardTitle>
        <CardDescription>
          Pins show purchases; dashed lines connect trips across cities within 7
          days
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <EmployeeMapFilter
            employees={employees}
            selectedIds={selectedIds}
            onSelectionChange={setSelectedIds}
          />
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label htmlFor="map-date-from" className="text-xs text-muted-foreground">
                From
              </Label>
              <Input
                id="map-date-from"
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="h-8 w-[140px] border-border/60"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="map-date-to" className="text-xs text-muted-foreground">
                To
              </Label>
              <Input
                id="map-date-to"
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="h-8 w-[140px] border-border/60"
              />
            </div>
          </div>
        </div>

        {purchasesError && (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm text-destructive">{purchasesError}</p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSelectedIds([...selectedIds])}
            >
              Retry
            </Button>
          </div>
        )}

        <div className="relative h-[min(50vh,480px)] min-h-[360px] w-full overflow-hidden rounded-lg ring-1 ring-border/50">
          {purchasesLoading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60">
              <CircleNotchIcon
                className="size-8 animate-spin text-muted-foreground"
                aria-hidden
              />
              <span className="sr-only">Loading map data…</span>
            </div>
          )}

          {showMap ? (
            <PurchaseMap
              employees={mapEmployees}
              colorIndex={colorIndex}
              boundsKey={boundsKey}
            />
          ) : (
            !purchasesLoading &&
            mapEmptyMessage && (
              <div className="flex h-full items-center justify-center px-4">
                <p className="text-center text-sm text-muted-foreground">
                  {mapEmptyMessage}
                </p>
              </div>
            )
          )}
        </div>

        <MapLegend
          employees={employees}
          selectedIds={selectedIds}
          colorIndex={colorIndex}
        />
      </CardContent>
    </Card>
  );
}
