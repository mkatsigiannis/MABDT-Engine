"""Renders formatted Digital Twin snapshots into the natural-language preamble for LLM prompts."""

from typing import Any


class DigitalTwinContextBuilder:
    """Turns formatter output into prose for LLM prompt injection."""

    def __init__(self):
        """Initialize the context builder."""
        pass

    def build_workstation_context(self, workstation_summary: dict[str, Any]) -> str:
        """
        Build natural language context for workstation data.

        Args:
            workstation_summary: Formatted workstation summary

        Returns:
            Natural language description of workstation status
        """
        if not workstation_summary or workstation_summary.get("total_workstations", 0) == 0:
            return "No workstation data is currently available."

        context_parts = []

        # Overall workstation count
        total_ws = workstation_summary["total_workstations"]
        context_parts.append(
            f"There are {total_ws} workstations currently monitored in the system."
        )

        # State distribution
        by_state = workstation_summary.get("by_state", {})
        if by_state:
            state_descriptions = []
            for state, ws_list in by_state.items():
                count = len(ws_list)
                state_clean = (
                    state.replace("Production_", "").replace("Andon", " Andon").replace("_", " ")
                )
                state_descriptions.append(f"{count} in {state_clean} state ({', '.join(ws_list)})")

            context_parts.append(f"Workstation status breakdown: {'; '.join(state_descriptions)}.")

        # Performance analysis
        performance_summary = workstation_summary.get("performance_summary", "")
        if performance_summary and performance_summary != "No workstation data available":
            context_parts.append(f"Performance analysis: {performance_summary}.")

        # Specific issues
        issues = workstation_summary.get("performance_issues", [])
        if issues:
            context_parts.append(f"Workstations requiring attention: {', '.join(issues)}.")

        # High performers
        high_performers = workstation_summary.get("high_performers", [])
        if high_performers:
            context_parts.append(f"High-utilization workstations: {', '.join(high_performers)}.")

        return " ".join(context_parts)

    def build_car_context(self, car_summary: dict[str, Any]) -> str:
        """
        Build natural language context for vehicle information with clear categorization.

        Args:
            car_summary: Formatted car summary with categorization

        Returns:
            Natural language description of vehicle status
        """
        if not car_summary or car_summary.get("total_cars", 0) == 0:
            return "No vehicles are currently in the system."

        context_parts = []
        total_cars = car_summary.get("total_cars", 0)

        # Vehicle counts by category
        active_cars = car_summary.get("active_cars", 0)
        inspection_cars = car_summary.get("inspection_cars", 0)
        finished_cars = car_summary.get("finished_cars", 0)
        unknown_cars = car_summary.get("unknown_cars", 0)

        # Main vehicle status summary with clear categorization
        status_parts = []
        if active_cars > 0:
            status_parts.append(
                f"{active_cars} vehicles actively in production (workstations 1-15)"
            )
        if inspection_cars > 0:
            status_parts.append(f"{inspection_cars} vehicles under inspection (inspection station)")
        if finished_cars > 0:
            status_parts.append(f"{finished_cars} vehicles COMPLETED and finished production")
        if unknown_cars > 0:
            status_parts.append(f"{unknown_cars} vehicles with unknown status")

        if status_parts:
            context_parts.append(f"Vehicle breakdown: {'; '.join(status_parts)}.")
        else:
            context_parts.append(f"Total of {total_cars} vehicles in the system.")

        # Vehicle locations for active cars
        by_location = car_summary.get("by_location", {})
        if by_location:
            location_summary = []
            for location, cars in by_location.items():
                if location != "Unknown" and len(cars) > 0:
                    location_summary.append(f"{len(cars)} at {location}")

            if location_summary:
                context_parts.append(f"Vehicle locations: {', '.join(location_summary)}.")

        # Vehicle states with categorization
        by_category = car_summary.get("by_category", {})
        if by_category:
            state_descriptions = []

            # Active production vehicles
            if by_category.get("active"):
                active_list = by_category["active"]
                state_descriptions.append(
                    f"{len(active_list)} in active production ({', '.join(active_list[:3])}{'...' if len(active_list) > 3 else ''})"
                )

            # Inspection vehicles
            if by_category.get("inspection"):
                inspection_list = by_category["inspection"]
                state_descriptions.append(
                    f"{len(inspection_list)} under inspection ({', '.join(inspection_list)})"
                )

            # Finished vehicles
            if by_category.get("finished"):
                finished_list = by_category["finished"]
                state_descriptions.append(
                    f"{len(finished_list)} FINISHED and completed ({', '.join(finished_list)})"
                )

            if state_descriptions:
                context_parts.append(f"Vehicle status details: {'; '.join(state_descriptions)}.")

        # Quality metrics with focus on finished cars
        fault_rate = car_summary.get("fault_rate_percent", 0)
        cars_with_faults = car_summary.get("cars_with_faults", 0)
        avg_faults = car_summary.get("average_faults_per_car", 0)

        if fault_rate > 0:
            quality_context = f"Quality analysis: {cars_with_faults} of {total_cars} vehicles have faults ({fault_rate:.1f}% fault rate), averaging {avg_faults:.1f} faults per vehicle."

            # Add fault context specific to finished cars
            if finished_cars > 0:
                # Calculate fault rate for finished cars specifically
                details = car_summary.get("details", [])
                finished_car_faults = [
                    d
                    for d in details
                    if d.get("category") == "finished" and d.get("total_faults", 0) > 0
                ]
                finished_fault_rate = (
                    (len(finished_car_faults) / finished_cars * 100) if finished_cars > 0 else 0
                )
                quality_context += f" Among completed vehicles: {len(finished_car_faults)} of {finished_cars} finished cars have faults ({finished_fault_rate:.1f}% defect rate)."

            if fault_rate > 50:
                quality_context += (
                    " This indicates significant quality issues requiring immediate attention."
                )
            elif fault_rate > 20:
                quality_context += " This fault rate is above normal and should be investigated."
            else:
                quality_context += " Fault rate is within acceptable limits."
            context_parts.append(quality_context)
        else:
            if finished_cars > 0:
                context_parts.append(
                    f"Quality status: All {finished_cars} finished vehicles passed inspection without faults."
                )
            else:
                context_parts.append(
                    "Quality status: All vehicles in production are currently fault-free."
                )

        return " ".join(context_parts)

    def build_production_context(self, metrics_summary: dict[str, Any]) -> str:
        """
        Build natural language context for production metrics with enhanced car categorization.

        Args:
            metrics_summary: Formatted production metrics with car breakdown

        Returns:
            Natural language description of production status
        """
        if not metrics_summary:
            return "No production metrics are currently available."

        context_parts = []

        production_tracking = metrics_summary.get("production_tracking", False)

        if production_tracking:
            context_parts.append(
                "The production system is currently ACTIVE and tracking production."
            )
        else:
            context_parts.append(
                "The production system is currently INACTIVE - production tracking is stopped."
            )

        # Performance targets
        targets = metrics_summary.get("targets", {})
        if targets:
            takt_time = targets.get("takt_time", 75)
            cycle_time = targets.get("cycle_time", 60)
            context_parts.append(
                f"Production targets: {takt_time}s takt time, {cycle_time}s cycle time."
            )

        # Current performance with enhanced car breakdown
        current_perf = metrics_summary.get("current_performance", {})
        car_breakdown = metrics_summary.get("car_breakdown", {})

        if current_perf:
            ws_count = current_perf.get("total_workstations", 0)
            total_cars = current_perf.get("total_cars_in_system", 0)

            context_parts.append(
                f"Facility status: {ws_count} workstations operational, {total_cars} total vehicles in system."
            )

        # Detailed car breakdown
        if car_breakdown:
            active_cars = car_breakdown.get("active_cars", 0)
            inspection_cars = car_breakdown.get("inspection_cars", 0)
            finished_cars = car_breakdown.get("finished_cars", 0)
            unknown_cars = car_breakdown.get("unknown_cars", 0)

            breakdown_parts = []
            if active_cars > 0:
                breakdown_parts.append(f"{active_cars} vehicles in active production")
            if inspection_cars > 0:
                breakdown_parts.append(f"{inspection_cars} vehicles under inspection")
            if finished_cars > 0:
                breakdown_parts.append(f"{finished_cars} vehicles COMPLETED production")
            if unknown_cars > 0:
                breakdown_parts.append(f"{unknown_cars} vehicles with unknown status")

            if breakdown_parts:
                context_parts.append(f"Vehicle categorization: {'; '.join(breakdown_parts)}.")

        return " ".join(context_parts)

    def build_comprehensive_context(self, formatted_data: dict[str, Any]) -> str:
        """
        Build comprehensive natural language context from all formatted data.

        Args:
            formatted_data: Complete formatted data from DigitalTwinContextFormatter

        Returns:
            Comprehensive natural language context for LLM prompts
        """
        if not formatted_data:
            return "No Digital Twin data is currently available for analysis."

        context_sections = []

        # Timestamp and overall status
        timestamp = formatted_data.get("timestamp", "Unknown")
        overall_status = formatted_data.get("overall_status", "Status unknown")

        context_sections.append("=== TIGER MOTORS DIGITAL TWIN STATUS ===")
        context_sections.append(f"Data Timestamp: {timestamp}")
        context_sections.append(f"{overall_status}")

        # Key insights
        key_insights = formatted_data.get("key_insights", [])
        if key_insights:
            context_sections.append("\nKEY INSIGHTS:")
            for i, insight in enumerate(key_insights, 1):
                context_sections.append(f"{i}. {insight}")

        # Production metrics context
        metrics_summary = formatted_data.get("metrics", {})
        if metrics_summary:
            context_sections.append("\nPRODUCTION SYSTEM:")
            context_sections.append(self.build_production_context(metrics_summary))

        # Workstation context
        workstation_summary = formatted_data.get("workstations", {})
        if workstation_summary and workstation_summary.get("total_workstations", 0) > 0:
            context_sections.append("\nWORKSTATION STATUS:")
            context_sections.append(self.build_workstation_context(workstation_summary))

        # Vehicle context
        car_summary = formatted_data.get("cars", {})
        if car_summary and car_summary.get("total_cars", 0) > 0:
            context_sections.append("\nVEHICLE STATUS:")
            context_sections.append(self.build_car_context(car_summary))

        # Data availability summary
        raw_data = formatted_data.get("raw_data_available", {})
        if raw_data:
            ws_count = raw_data.get("workstation_count", 0)
            car_count = raw_data.get("car_count", 0)
            has_metrics = raw_data.get("has_metrics", False)
            context_sections.append(
                f"\nDATA AVAILABILITY: {ws_count} workstations, {car_count} vehicles, metrics {'available' if has_metrics else 'unavailable'}"
            )

        return "\n".join(context_sections)

    def build_focused_context(
        self, formatted_data: dict[str, Any], focus_area: str = "overview"
    ) -> str:
        """
        Build focused context for specific areas of interest.

        Args:
            formatted_data: Complete formatted data
            focus_area: Area to focus on ("overview", "workstations", "vehicles", "quality", "performance")

        Returns:
            Focused natural language context
        """
        if not formatted_data:
            return "No Digital Twin data is currently available."

        if focus_area == "workstations":
            workstation_summary = formatted_data.get("workstations", {})
            return self.build_workstation_context(workstation_summary)

        elif focus_area == "vehicles":
            car_summary = formatted_data.get("cars", {})
            return self.build_car_context(car_summary)

        elif focus_area == "quality":
            car_summary = formatted_data.get("cars", {})
            if not car_summary or car_summary.get("total_cars", 0) == 0:
                return "No quality data available - no vehicles in production."

            fault_rate = car_summary.get("fault_rate_percent", 0)
            cars_with_faults = car_summary.get("cars_with_faults", 0)
            total_cars = car_summary.get("total_cars", 0)

            return (
                f"Quality Analysis: {cars_with_faults} of {total_cars} vehicles have faults ({fault_rate:.1f}% fault rate). "
                + f"Total faults detected: {car_summary.get('total_faults', 0)}. "
                + f"Quality summary: {car_summary.get('quality_summary', 'No summary available')}."
            )

        elif focus_area == "performance":
            metrics_summary = formatted_data.get("metrics", {})
            workstation_summary = formatted_data.get("workstations", {})

            context_parts = []
            context_parts.append(self.build_production_context(metrics_summary))

            if workstation_summary.get("performance_issues"):
                context_parts.append(
                    f"Performance issues detected: {', '.join(workstation_summary['performance_issues'])}."
                )

            if workstation_summary.get("high_performers"):
                context_parts.append(
                    f"High-performing workstations: {', '.join(workstation_summary['high_performers'])}."
                )

            return " ".join(context_parts)

        else:  # overview or unknown
            overall_status = formatted_data.get("overall_status", "Status unknown")
            key_insights = formatted_data.get("key_insights", [])

            context = overall_status
            if key_insights:
                context += (
                    f" Key issues: {'; '.join(key_insights[:2])}."  # First 2 insights for overview
                )

            return context

    def get_context_summary_stats(self, formatted_data: dict[str, Any]) -> str:
        """
        Get a brief statistical summary for context validation.

        Args:
            formatted_data: Complete formatted data

        Returns:
            Brief statistical summary
        """
        if not formatted_data:
            return "No data"

        ws_count = formatted_data.get("workstations", {}).get("total_workstations", 0)
        car_count = formatted_data.get("cars", {}).get("total_cars", 0)
        tracking = formatted_data.get("metrics", {}).get("production_tracking", False)

        return f"Data: {ws_count} WS, {car_count} cars, tracking: {tracking}"
