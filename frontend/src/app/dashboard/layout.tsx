import { TopBar } from "@/components/layout/TopBar";
import { TabBar } from "@/components/layout/TabBar";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <TopBar />
      <TabBar />
      <main className="flex-1 p-6">{children}</main>
    </div>
  );
}
