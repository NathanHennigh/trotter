import type { PlannerExclusionReason, PlannerIdea, PlannerPlan, PlannerTransport } from '../../../services/planner';
import { isStayIdea } from './plannerEditing';

const count = (value: number, one: string, many: string) => `${value} ${value === 1 ? one : many}`;
export function savedIdeaSummary(ideas: PlannerIdea[]) {
  const stays = ideas.filter(isStayIdea).length;
  return `${count(ideas.length - stays, 'activity', 'activities')} · ${count(stays, 'stay option', 'stay options')}`;
}
export function stayOptionsSummary(ideas: PlannerIdea[]) {
  return count(ideas.filter(isStayIdea).length, 'saved stay option', 'saved stay options');
}
export function plannedActivitySummary(plan: PlannerPlan, ideas: PlannerIdea[]) {
  const activities = new Set(ideas.filter(idea => !isStayIdea(idea)).map(idea => idea.id));
  const planned = new Set(plan.days.flatMap(day => day.stops.map(stop => stop.idea_id).filter((id): id is string => !!id && activities.has(id))));
  return `${planned.size} of ${count(activities.size, 'activity', 'activities')} planned`;
}
export function unscheduledActivities(plan: PlannerPlan, ideas: PlannerIdea[]) {
  const planned = new Set(plan.days.flatMap(day => day.stops.map(stop => stop.idea_id)));
  return ideas.filter(idea => !isStayIdea(idea) && !planned.has(idea.id));
}
export function transportReasonApplies(reason: PlannerExclusionReason | undefined, modes: readonly PlannerTransport[]) {
  return reason?.code === 'transport_required' && modes.length === 1 && modes[0] === reason.transport_mode;
}
export function currentExclusionReason(idea: PlannerIdea, reason: PlannerExclusionReason | undefined) {
  if (reason?.code === 'needs_location' && idea.title && (idea.city || (Number.isFinite(idea.latitude) && Number.isFinite(idea.longitude)))) return undefined;
  if (reason?.code === 'processing' && idea.status !== 'processing') return undefined;
  if (reason?.code === 'low_interest' && (idea.score >= 0 || idea.must_do)) return undefined;
  return reason;
}
export function exclusionText(reason: PlannerExclusionReason | undefined, modes: readonly PlannerTransport[]) {
  if (transportReasonApplies(reason, modes)) return reason?.transport_mode === 'walk'
    ? 'Needs transport beyond walking for this plan.' : 'This journey needs more travel time.';
  switch (reason?.code) {
    case 'needs_location': return 'Add a city or location before planning this stop.';
    case 'processing': return 'Places are still being found in this save.';
    case 'closed': return 'Marked closed when this plan was made.';
    case 'opening_hours': return 'No visit window fitted the dates being planned.';
    case 'travel_unverified': return 'The connection to this place still needs checking.';
    case 'low_interest': return 'Left out based on the group’s votes.';
    case 'duplicate': return 'This place is already represented in the itinerary.';
    default: return 'Not included in this version.';
  }
}
