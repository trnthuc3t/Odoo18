from odoo import models, fields, api

class TourWebsite(models.Model):
    _name = 'tour.website'
    _description = 'Tour Website'

    name = fields.Char(string='Website Name', required=True)
    short_name = fields.Char(string='Short Name', required=True)
    url = fields.Char(string='Website URL', required=True)
    pricelist_id = fields.Many2one(
        comodel_name='product.pricelist',
        string='Pricelist'
    )
    is_active = fields.Boolean(string='Is Active', default=True)

    @api.model
    def get_active_websites(self):
        """Retrieve all active tour websites."""
        return self.search([('is_active', '=', True)])
    
    @api.model
    def get_website_by_short_name(self, short_name):
        """Retrieve an tour website by its short name."""
        return self.search([('short_name', '=', short_name)], limit=1)
    
    @api.model
    def name_get(self):
        """Customize the display name of the tour website."""
        result = []
        for record in self:
            display_name = f"{record.name} ({record.short_name})"
            result.append((record.id, display_name))
        return result
