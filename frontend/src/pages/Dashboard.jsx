import { lazy, Suspense } from 'react'

const MarketDashboard = lazy(() => import('../features/market-dashboard/MarketDashboard.jsx'))

export default function Dashboard(){
     return (
          <Suspense fallback={null}>
               <MarketDashboard />
          </Suspense>
     )
}
