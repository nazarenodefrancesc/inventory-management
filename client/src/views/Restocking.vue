<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <!-- Success banner after placing an order -->
      <div v-if="successOrder" class="success-banner">
        <span>{{ t('restocking.orderPlaced', { orderNumber: successOrder.order_number }) }}</span>
        <button class="btn-link" @click="goToOrders">{{ t('restocking.viewOrders') }}</button>
      </div>

      <!-- Budget control card -->
      <div class="card budget-card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budget') }}</h3>
        </div>
        <div class="budget-body">
          <div class="budget-readout">{{ formatCurrency(budget, currentCurrency) }}</div>
          <input
            type="range"
            class="budget-slider"
            min="0"
            :max="maxBudget"
            step="100"
            v-model.number="budget"
          />
          <p class="budget-help">{{ t('restocking.budgetHelp') }}</p>
        </div>
      </div>

      <!-- Summary stat tiles -->
      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.selectedItems') }}</div>
          <div class="stat-value">{{ selectedRecommendations.length }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value stat-value--sm">{{ formatCurrency(totalCost, currentCurrency) }}</div>
        </div>
        <div class="stat-card" :class="budgetRemaining >= 0 ? 'warning' : 'danger'">
          <div class="stat-label">{{ t('restocking.budgetRemaining') }}</div>
          <div class="stat-value stat-value--sm">{{ formatCurrency(budgetRemaining, currentCurrency) }}</div>
        </div>
      </div>

      <!-- Recommendations table card -->
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }}</h3>
        </div>

        <div v-if="maxBudget === 0" class="no-recommendations">
          {{ t('restocking.noRecommendations') }}
        </div>

        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.onHand') }}</th>
                <th>{{ t('restocking.table.reorderPoint') }}</th>
                <th>{{ t('restocking.table.restockQty') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineCost') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in selectedRecommendations" :key="row.sku">
                <td><strong>{{ row.sku }}</strong></td>
                <td>{{ row.name }}</td>
                <td>
                  <span :class="['badge', row.trend]">{{ t('trends.' + row.trend) }}</span>
                </td>
                <td>{{ row.onHand }}</td>
                <td><strong>{{ row.reorderPoint }}</strong></td>
                <td><strong>{{ row.shortfall }}</strong></td>
                <td>{{ formatCurrencyWithDecimals(row.unitCost, currentCurrency, 2) }}</td>
                <td>{{ formatCurrency(row.lineCost, currentCurrency) }}</td>
                <td>{{ t('orders.leadTimeDays', { days: leadTimeForTrend(row.trend) }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="maxBudget > 0" class="card-footer">
          <button
            class="btn-primary"
            :disabled="selectedRecommendations.length === 0 || placing"
            @click="placeOrder"
          >
            {{ placing ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useFilters } from '../composables/useFilters'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()
    const { selectedLocation, selectedCategory, getCurrentFilters } = useFilters()
    const router = useRouter()

    // --- State ---
    const loading = ref(true)
    const error = ref(null)
    const allForecasts = ref([])
    const inventoryItems = ref([])
    const budget = ref(0)
    const budgetInitialized = ref(false)
    const placing = ref(false)
    const successOrder = ref(null)

    // --- Data loading (mirrors Demand.vue: Promise.all + watch on filters) ---
    const loadData = async () => {
      try {
        loading.value = true
        error.value = null
        const filters = getCurrentFilters()

        const [forecastsData, inventoryData] = await Promise.all([
          api.getDemandForecasts(),
          api.getInventory({ warehouse: filters.warehouse, category: filters.category })
        ])

        allForecasts.value = forecastsData
        inventoryItems.value = inventoryData
      } catch (err) {
        error.value = 'Failed to load restocking data: ' + err.message
      } finally {
        loading.value = false
      }
    }

    onMounted(loadData)
    watch([selectedLocation, selectedCategory], loadData)

    // --- Candidates: inventory items at/below their reorder point.
    // Demand trend (when the SKU is forecasted) only sets priority/lead time;
    // it is no longer used to compute the shortfall quantity. ---
    const candidates = computed(() => {
      const trendMap = new Map(allForecasts.value.map(f => [f.item_sku, f.trend]))

      return inventoryItems.value.reduce((acc, item) => {
        const shortfall = Math.max(0, item.reorder_point - item.quantity_on_hand)
        if (shortfall > 0) {
          const unitCost = item.unit_cost
          acc.push({
            sku: item.sku,
            name: item.name,
            trend: trendMap.get(item.sku) || 'stable',
            onHand: item.quantity_on_hand,
            reorderPoint: item.reorder_point,
            shortfall,
            unitCost,
            lineCost: shortfall * unitCost
          })
        }
        return acc
      }, [])
    })

    // --- trendWeight: lower = higher priority (increasing demand is most urgent) ---
    const trendWeight = (trend) => {
      return { increasing: 0, stable: 1, decreasing: 2 }[trend] ?? 1
    }

    // --- rankedCandidates: sort by trendWeight asc, then shortfall desc ---
    const rankedCandidates = computed(() => {
      return candidates.value.slice().sort((a, b) => {
        const tw = trendWeight(a.trend) - trendWeight(b.trend)
        if (tw !== 0) return tw
        return b.shortfall - a.shortfall
      })
    })

    // --- maxBudget: total cost of all candidates (ceiling to nearest integer) ---
    const maxBudget = computed(() => {
      const total = rankedCandidates.value.reduce((sum, c) => sum + c.lineCost, 0)
      return Math.ceil(total)
    })

    // --- Seed the slider to half of maxBudget on first load; thereafter only
    // re-clamp (never re-seed) so a filter change that shrinks the candidate
    // set can't leave the budget stranded above the new maximum. ---
    watch(maxBudget, (val) => {
      if (!budgetInitialized.value && val > 0) {
        budget.value = Math.round(val / 2)
        budgetInitialized.value = true
      } else if (budgetInitialized.value && budget.value > val) {
        budget.value = val
      }
    })

    // --- selectedRecommendations: greedy selection by priority order ---
    // Walk rankedCandidates in priority order (increasing trend first, then largest shortfall).
    // Include an item if its lineCost fits within the remaining budget, then continue checking
    // remaining items so that cheaper lower-priority items can still consume leftover budget.
    const selectedRecommendations = computed(() => {
      let runningTotal = 0
      const included = []

      for (const item of rankedCandidates.value) {
        if (runningTotal + item.lineCost <= budget.value) {
          included.push(item)
          runningTotal += item.lineCost
        }
        // Do not break: continue so cheaper lower-ranked items can fill remaining budget
      }

      return included
    })

    // --- Summary computed values ---
    const totalCost = computed(() =>
      selectedRecommendations.value.reduce((sum, r) => sum + r.lineCost, 0)
    )

    const budgetRemaining = computed(() => budget.value - totalCost.value)

    // --- leadTimeForTrend: mirrors backend LEAD_TIME_BY_TREND ---
    const leadTimeForTrend = (trend) => {
      return { increasing: 7, stable: 14, decreasing: 21 }[trend] ?? 14
    }

    // --- placeOrder ---
    const placeOrder = async () => {
      if (selectedRecommendations.value.length === 0 || placing.value) return

      placing.value = true
      try {
        const payload = {
          items: selectedRecommendations.value.map(r => ({
            sku: r.sku,
            name: r.name,
            quantity: r.shortfall,
            unit_price: r.unitCost,
            trend: r.trend
          }))
        }
        const order = await api.createRestockOrder(payload)
        successOrder.value = order
      } catch (err) {
        error.value = 'Failed to place restock order: ' + err.message
      } finally {
        placing.value = false
      }
    }

    // --- goToOrders ---
    const goToOrders = () => {
      router.push('/orders')
    }

    return {
      t,
      currentCurrency,
      loading,
      error,
      budget,
      placing,
      successOrder,
      maxBudget,
      selectedRecommendations,
      totalCost,
      budgetRemaining,
      formatCurrency,
      formatCurrencyWithDecimals,
      leadTimeForTrend,
      placeOrder,
      goToOrders
    }
  }
}
</script>

<style scoped>
.restocking {
  /* Page wrapper — global styles handle the rest */
}

/* ---- Budget card ---- */
.budget-card {
  margin-bottom: 1.25rem;
}

.budget-body {
  padding: 1.25rem 1.5rem 1.5rem;
}

.budget-readout {
  font-size: 2.5rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
  margin-bottom: 0.75rem;
}

.budget-slider {
  width: 100%;
  height: 6px;
  accent-color: #3b82f6;
  cursor: pointer;
  margin-bottom: 0.625rem;
}

.budget-help {
  font-size: 0.813rem;
  color: #64748b;
  margin: 0;
}

/* ---- Stat tiles ---- */
.stat-value--sm {
  font-size: 1.5rem;
}

/* ---- No recommendations message ---- */
.no-recommendations {
  padding: 2rem 1.5rem;
  color: #64748b;
  font-size: 0.938rem;
  text-align: center;
}

/* ---- Card footer (Place Order button) ---- */
.card-footer {
  padding: 1rem 1.5rem 0.5rem;
  border-top: 1px solid #e2e8f0;
  margin-top: 1rem;
  display: flex;
  justify-content: flex-end;
}

/* ---- Primary action button ---- */
.btn-primary {
  background: #3b82f6;
  color: white;
  border: none;
  padding: 0.625rem 1.5rem;
  border-radius: 8px;
  font-size: 0.938rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #2563eb;
}

.btn-primary:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

/* ---- Success banner ---- */
.success-banner {
  display: flex;
  align-items: center;
  gap: 1rem;
  background: #d1fae5;
  border: 1px solid #6ee7b7;
  border-radius: 8px;
  padding: 0.875rem 1.25rem;
  margin-bottom: 1.25rem;
  color: #065f46;
  font-size: 0.938rem;
  font-weight: 500;
}

.btn-link {
  background: none;
  border: none;
  color: #059669;
  font-size: 0.938rem;
  font-weight: 600;
  cursor: pointer;
  text-decoration: underline;
  padding: 0;
}

.btn-link:hover {
  color: #065f46;
}

/* ---- Trend badges (scoped overrides for the specific colours in spec) ---- */
.badge.increasing {
  background: #d1fae5;
  color: #059669;
}

.badge.stable {
  background: #dbeafe;
  color: #2563eb;
}

.badge.decreasing {
  background: #fee2e2;
  color: #dc2626;
}
</style>
