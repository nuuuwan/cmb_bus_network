from cbn.core.Place import Place

if __name__ == "__main__":
    Place.fill_all_latlng()
    Place.remove_too_far()
    Place.remove_all_but_closest()
    Place.analyze_coverage()
    Place.plot()
    Place.open_uncovered_gnds_in_google_maps(limit=10)
